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

    # Optimistic echo renders the tag immediately, before the DB write lands.
    assert any("task-urgent" in (m.value or "") and title in (m.value or "")
               for m in at.markdown), "Urgent tag missing from the optimistic echo"
    print("PASS: urgent checkbox in the form renders the דחוף tag instantly")

    at = _wait_for_sync(at)
    row = next(t for t in db.get_tasks(project_id=pid) if t["title"] == title)
    assert row["is_urgent"] is True, "Form-created task was not marked urgent in the DB"
    assert any("task-urgent" in (m.value or "") and title in (m.value or "")
               for m in at.markdown), "Urgent tag missing after sync"
    print("PASS: form-created urgent task saved to Supabase and tagged in the list")
    return at, row


def test_completed_urgent_is_dimmed(at, row):
    db.set_task_done(row["id"], True, TEMP_ADMIN)
    db.get_tasks.clear()
    at = at.run()
    html_blocks = [m.value or "" for m in at.markdown if row["title"] in (m.value or "")]
    assert html_blocks, "Task not rendered"
    block = html_blocks[0]
    assert "task-done" in block and "<s>" in block, f"Completed task not struck/dimmed: {block}"
    assert "task-urgent" in block, "Urgent tag should survive completion"
    print("PASS: completed urgent task is struck through, dimmed, and keeps its tag")


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
    finally:
        _cleanup()
    print("\nALL URGENT-TASK TESTS PASSED")
