"""Verify urgency (3-level: נמוך/בינוני/גבוה) against the real Supabase database.

Run with:  python test_urgent_tasks.py

is_urgent (boolean) is kept as an internal mirror of urgency — True only when
urgency == 'גבוה' — so get_urgent_open_tasks(), the home-screen widget and
notify_urgent_assignment() (all keyed on is_urgent, already relying on this
file's coverage) needed no changes when urgency became a 3-level field.

Covers:
  1. is_urgent column exists and defaults to FALSE; urgency defaults to בינוני.
  2. add_task(is_urgent=True) persists both is_urgent and urgency=גבוה.
  3. Ordering: open urgent (is_urgent) tasks sort above open regular tasks.
  4. The task-creation form's urgent checkbox creates a task with urgency=
     גבוה (AppTest), and the pending echo renders the urgency pill for it.
  5. A completed urgent task keeps both dropdowns (status, urgency).
  6. The urgency dropdown round-trips through all 3 levels via the real UI,
     keeping is_urgent in sync at every step.
"""

import time

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_urgent_project"


def _project_id() -> int:
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    return row["id"] if row else None


def _cleanup():
    pid = _project_id()
    if pid:
        db.delete_project(pid)
    cleanup()


def _ss(at, key, default=None):
    return at.session_state[key] if key in at.session_state else default


def _wait_for_sync(at, seconds=6):
    deadline = time.time() + seconds
    while time.time() < deadline and _ss(at, "_pending_writes"):
        time.sleep(0.3)
    time.sleep(0.5)
    return at.run()


def test_column_default():
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    db.add_task("רגילה", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    task = db.get_tasks(project_id=pid)[0]
    assert "is_urgent" in task, "tasks table is missing the is_urgent column"
    assert task["is_urgent"] is False, f"Default should be FALSE, got {task['is_urgent']!r}"
    print("PASS: is_urgent column exists and defaults to FALSE")
    return pid


def test_urgent_persists(pid):
    db.add_task("דחופה", TEMP_ADMIN, TEMP_ADMIN, pid, "project", is_urgent=True)
    tasks = db.get_tasks(project_id=pid)
    urgent = next(t for t in tasks if t["title"] == "דחופה")
    assert urgent["is_urgent"] is True, "is_urgent was not saved"
    print("PASS: add_task(is_urgent=True) persists the flag to Supabase")


def test_ordering(pid):
    titles = [t["title"] for t in db.get_tasks(project_id=pid) if not t["is_done"]]
    assert titles.index("דחופה") < titles.index("רגילה"), (
        f"Urgent task should sort first, got {titles}"
    )
    print("PASS: open urgent tasks sort above regular ones")


def test_toggle_urgency(pid):
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "רגילה")
    db.set_task_urgent(task["id"], True)
    assert next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_urgent"] is True
    db.set_task_urgent(task["id"], False)
    assert next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_urgent"] is False
    print("PASS: set_task_urgent toggles the flag both ways")


def test_form_creates_urgent_task(pid):
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, f"Dashboard crashed: {at.exception[0]}"

    scope = f"project_{pid}"
    title = f"דחוף מהטופס {int(time.time())}"
    at.text_input(key=f"task_title_{scope}").set_value(title)
    at.checkbox(key=f"task_urgent_{scope}").set_value(True)
    submit = next(b for b in at.button if b.key == f"add_task_submit_{scope}")
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"

    # The pending echo renders the urgency pill immediately (it has no DB id yet).
    assert any("urgency-high" in (m.value or "") and title in (m.value or "")
               for m in at.markdown), "Urgency pill missing from the optimistic echo"
    print("PASS: urgent checkbox in the form renders the urgency pill instantly")

    at = _wait_for_sync(at)
    row = next(t for t in db.get_tasks(project_id=pid) if t["title"] == title)
    assert row["is_urgent"] is True, "Form-created task was not marked urgent in the DB"
    assert row["urgency"] == db.URGENCY_HIGH, f"Expected urgency=גבוה, got {row['urgency']!r}"
    # Once synced, urgency is shown by the interactive dropdown.
    urgency_select = next(
        (s for s in at.selectbox if s.key == f"task_urgency_{row['id']}"), None
    )
    assert urgency_select is not None, "Urgency dropdown missing"
    assert urgency_select.value == db.URGENCY_HIGH, "Dropdown should show גבוה"
    print("PASS: form-created urgent task saved to Supabase and shows in the dropdown")
    return at, row


def test_completed_urgent_is_dimmed(at, row):
    db.set_task_done(row["id"], True, TEMP_ADMIN)
    db.clear_task_caches()
    at = at.run()
    html_blocks = [m.value or "" for m in at.markdown if row["title"] in (m.value or "")]
    assert html_blocks, "Task not rendered"
    block = html_blocks[0]
    assert "task-done" in block and "<s>" in block, f"Completed task not struck/dimmed: {block}"
    urgency_select = next(s for s in at.selectbox if s.key == f"task_urgency_{row['id']}")
    assert urgency_select.value == db.URGENCY_HIGH, "Urgency should survive completion"
    status = next(s for s in at.selectbox if s.key == f"task_status_{row['id']}")
    assert status.value == db.STATUS_DONE, f"Status dropdown should show {db.STATUS_DONE!r}"
    print("PASS: completed urgent task is struck through, dimmed, and keeps both controls")


def test_ui_urgency_dropdown_round_trip(pid):
    """Flip urgency from the task list, through all 3 levels, through the real UI."""
    db.add_task("משימה לסימון דחיפות", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    db.clear_task_caches()
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "משימה לסימון דחיפות")
    assert task["urgency"] == db.URGENCY_MEDIUM, f"Expected the neutral default, got {task['urgency']!r}"

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    urgency_key = f"task_urgency_{task['id']}"
    dropdown = next(s for s in at.selectbox if s.key == urgency_key)
    at = dropdown.set_value(db.URGENCY_HIGH).run()
    assert not at.exception, f"Urgency change crashed: {at.exception[0]}"
    # Optimistic: the new level shows before the DB write is confirmed.
    dropdown = next(s for s in at.selectbox if s.key == urgency_key)
    assert dropdown.value == db.URGENCY_HIGH, "Urgency should flip instantly (optimistic)"
    print("PASS: selecting גבוה marks a task urgent instantly (optimistic)")

    at = _wait_for_sync(at)
    db.clear_task_caches()
    fresh = next(t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"])
    assert fresh["urgency"] == db.URGENCY_HIGH and fresh["is_urgent"] is True
    assert task["id"] not in _ss(at, "task_urgency_override", {}), "Override should be pruned"
    print("PASS: urgency change synced to Supabase (urgency + is_urgent both updated)")

    dropdown = next(s for s in at.selectbox if s.key == urgency_key)
    at = dropdown.set_value(db.URGENCY_LOW).run()
    assert not at.exception, f"Urgency change crashed: {at.exception[0]}"
    at = _wait_for_sync(at)
    db.clear_task_caches()
    fresh = next(t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"])
    assert fresh["urgency"] == db.URGENCY_LOW and fresh["is_urgent"] is False, (
        "Selecting the LOW level must also clear is_urgent"
    )
    print("PASS: selecting נמוך clears is_urgent and syncs")
    return at, task


def test_ui_status_dropdown_round_trip(pid, task):
    """The status dropdown reversibly moves a task between open and done."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    status_key = f"task_status_{task['id']}"
    dropdown = next(s for s in at.selectbox if s.key == status_key)
    assert dropdown.value == db.STATUS_IN_PROGRESS, f"Expected an open task, got {dropdown.value!r}"

    at = dropdown.set_value(db.STATUS_DONE).run()
    assert not at.exception, f"Status change crashed: {at.exception[0]}"
    # Optimistic: the new value shows before the DB write is confirmed.
    dropdown = next(s for s in at.selectbox if s.key == status_key)
    assert dropdown.value == db.STATUS_DONE, "Status should flip instantly (optimistic)"
    print("PASS: selecting בוצע marks the task done instantly (optimistic)")

    at = _wait_for_sync(at)
    db.clear_task_caches()
    assert next(t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"])["is_done"], (
        "Status change did not sync to Supabase"
    )
    assert task["id"] not in _ss(at, "task_status_override", {}), "Override should be pruned"
    print("PASS: status change synced to Supabase and the override was pruned")

    dropdown = next(s for s in at.selectbox if s.key == status_key)
    at = dropdown.set_value(db.STATUS_IN_PROGRESS).run()
    assert not at.exception, f"Reopen crashed: {at.exception[0]}"
    at = _wait_for_sync(at)
    db.clear_task_caches()
    assert not next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_done"], "Reopening via the dropdown did not sync to the database"
    print("PASS: switching back to בתהליך reopens the task and syncs to Supabase")


def test_no_rerun_loop(pid):
    """Rendering the list repeatedly must be stable (no state churn / rerun loop).

    Explicitly covers the new status dropdown: an on_change callback that
    (incorrectly) forced its own rerun on top of Streamlit's automatic
    post-callback rerun wouldn't necessarily show up as a hang here, but it
    WOULD show up as churn in the control set or a leftover override —
    exactly what this asserts against.
    """
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    first = sorted(b.key for b in at.button if b.key)
    first_selects = sorted(s.key for s in at.selectbox if s.key)
    for _ in range(3):
        at = at.run()
        assert not at.exception, f"Re-render crashed: {at.exception[0]}"
    assert sorted(b.key for b in at.button if b.key) == first, "Controls changed between reruns"
    assert sorted(s.key for s in at.selectbox if s.key) == first_selects, (
        "Selectboxes changed between reruns"
    )
    assert not _ss(at, "task_urgency_override", {}), "Stale urgency overrides left behind"
    assert not _ss(at, "task_status_override", {}), "Stale status overrides left behind"
    print("PASS: repeated reruns are stable — no rerun loop, no stale overrides")


if __name__ == "__main__":
    _cleanup()
    create_temp_admin()
    try:
        pid = test_column_default()
        test_urgent_persists(pid)
        test_ordering(pid)
        test_toggle_urgency(pid)
        at, row = test_form_creates_urgent_task(pid)
        test_completed_urgent_is_dimmed(at, row)
        at, task = test_ui_urgency_dropdown_round_trip(pid)
        test_ui_status_dropdown_round_trip(pid, task)
        test_no_rerun_loop(pid)
    finally:
        _cleanup()
    print("\nALL URGENT-TASK TESTS PASSED")
