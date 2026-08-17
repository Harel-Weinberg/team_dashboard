"""Verify the "urgent" (דחוף) task status against the real Supabase database.

Run with:  python test_urgent_tasks.py

Covers:
  1. is_urgent column exists and defaults to FALSE.
  2. add_task(is_urgent=True) persists the flag.
  3. Ordering: open urgent tasks sort above open regular tasks.
  4. The task-creation form's urgent checkbox creates an urgent task (AppTest),
     and the list renders the red "דחוף" tag for it.
  5. A completed urgent task keeps its tag inside the dimmed wrapper.
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
    submit = next(b for b in at.button if b.key and f"add_task_form_{scope}" in b.key)
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"

    # The pending echo renders the inline tag immediately (it has no DB id yet).
    assert any("task-urgent" in (m.value or "") and title in (m.value or "")
               for m in at.markdown), "Urgent tag missing from the optimistic echo"
    print("PASS: urgent checkbox in the form renders the דחוף tag instantly")

    at = _wait_for_sync(at)
    row = next(t for t in db.get_tasks(project_id=pid) if t["title"] == title)
    assert row["is_urgent"] is True, "Form-created task was not marked urgent in the DB"
    # Once synced, urgency is shown by the interactive toggle (active state).
    keys = [b.key for b in at.button if b.key]
    assert f"task_urgent_on_{row['id']}" in keys, f"Active urgency toggle missing: {keys}"
    print("PASS: form-created urgent task saved to Supabase and shows the active toggle")
    return at, row


def test_completed_urgent_is_dimmed(at, row):
    db.set_task_done(row["id"], True, TEMP_ADMIN)
    db.get_tasks.clear()
    at = at.run()
    html_blocks = [m.value or "" for m in at.markdown if row["title"] in (m.value or "")]
    assert html_blocks, "Task not rendered"
    block = html_blocks[0]
    assert "task-done" in block and "<s>" in block, f"Completed task not struck/dimmed: {block}"
    keys = [b.key for b in at.button if b.key]
    assert f"task_urgent_on_{row['id']}" in keys, "Urgency toggle should survive completion"
    assert f"task_undone_{row['id']}" in keys, "Completed task should show the green הושלם pill"
    print("PASS: completed urgent task is struck through, dimmed, and keeps both controls")


def test_ui_urgency_toggle(pid):
    """Flip urgency from the task list, in both directions, through the real UI."""
    db.add_task("משימה לסימון דחיפות", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    db.get_tasks.clear()
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "משימה לסימון דחיפות")
    assert task["is_urgent"] is False

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    off_button = next(b for b in at.button if b.key == f"task_urgent_off_{task['id']}")
    at = off_button.set_value(True).run()
    assert not at.exception, f"Toggle crashed: {at.exception[0]}"
    # Optimistic: the active toggle shows before the DB write is confirmed.
    assert any(b.key == f"task_urgent_on_{task['id']}" for b in at.button), (
        "Urgency should flip instantly (optimistic)"
    )
    print("PASS: clicking the greyed 🔥 marks a task urgent instantly (optimistic)")

    at = _wait_for_sync(at)
    db.get_tasks.clear()
    assert next(t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"])["is_urgent"]
    assert task["id"] not in _ss(at, "task_urgent_override", {}), "Override should be pruned"
    print("PASS: urgency change synced to Supabase and the override was pruned")

    on_button = next(b for b in at.button if b.key == f"task_urgent_on_{task['id']}")
    at = on_button.set_value(True).run()
    assert any(b.key == f"task_urgent_off_{task['id']}" for b in at.button), (
        "Clicking the active toggle should clear urgency"
    )
    at = _wait_for_sync(at)
    db.get_tasks.clear()
    assert not next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_urgent"]
    print("PASS: clicking the active 🔥 דחוף clears urgency and syncs")
    return at, task


def test_ui_uncomplete_pill(pid, task):
    """The green הושלם pill reverts a completed task to open."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    at.checkbox(key=f"task_done_{task['id']}").set_value(True)
    at = at.run()
    assert any(b.key == f"task_undone_{task['id']}" for b in at.button), (
        "Completed task should show the green הושלם pill instead of a checkbox"
    )
    assert not any(c.key == f"task_done_{task['id']}" for c in at.checkbox), (
        "The checkbox should be replaced once the task is completed"
    )
    print("PASS: completing a task replaces the checkbox with the ✅ הושלם pill")

    at = _wait_for_sync(at)
    undone = next(b for b in at.button if b.key == f"task_undone_{task['id']}")
    at = undone.set_value(True).run()
    assert not at.exception, f"Un-complete crashed: {at.exception[0]}"
    assert any(c.key == f"task_done_{task['id']}" for c in at.checkbox), (
        "Clicking הושלם should bring the checkbox back (task reopened)"
    )
    at = _wait_for_sync(at)
    db.get_tasks.clear()
    assert not next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_done"], "Un-complete did not sync to the database"
    print("PASS: clicking ✅ הושלם reopens the task and syncs to Supabase")


def test_no_rerun_loop(pid):
    """Rendering the list repeatedly must be stable (no state churn / rerun loop)."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    first = sorted(b.key for b in at.button if b.key)
    for _ in range(3):
        at = at.run()
        assert not at.exception, f"Re-render crashed: {at.exception[0]}"
    assert sorted(b.key for b in at.button if b.key) == first, "Controls changed between reruns"
    assert not _ss(at, "task_urgent_override", {}), "Stale urgency overrides left behind"
    assert not _ss(at, "task_done_override", {}), "Stale completion overrides left behind"
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
        at, task = test_ui_urgency_toggle(pid)
        test_ui_uncomplete_pill(pid, task)
        test_no_rerun_loop(pid)
    finally:
        _cleanup()
    print("\nALL URGENT-TASK TESTS PASSED")
