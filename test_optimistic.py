"""Verify the Optimistic UI: instant local echoes, background sync, error surfacing.

Run with:  python test_optimistic.py

Uses a temporary admin + temporary project on the real database; cleans up after itself.
"""

import time

from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, create_temp_admin, login, new_app
from test_login_flow import cleanup as cleanup_users

TEMP_PROJECT = "temp_test_project_delete_me"


def _delete_temp_project():
    import database as db

    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])


def _ss(at, key, default=None):
    """AppTest's session_state proxy has no .get() — emulate it."""
    return at.session_state[key] if key in at.session_state else default


def _wait_for_sync(at, seconds=6):
    """Give background futures time to land, then rerun to reconcile."""
    deadline = time.time() + seconds
    while time.time() < deadline and _ss(at, "_pending_writes"):
        time.sleep(0.3)
    time.sleep(0.5)
    return at.run()


def _find_button(at, key_fragment):
    return next(b for b in at.button if b.key and key_fragment in b.key)


def _visible(at, text):
    return any(text in (m.value or "") for m in at.markdown)


def test_optimistic_project_creation(at):
    at.text_input(key="new_project_name").set_value(TEMP_PROJECT)
    t = time.perf_counter()
    at = _find_button(at, "add_project_form").set_value(True).run()
    elapsed = (time.perf_counter() - t) * 1000
    view = at.session_state["view"]
    # The background insert may land within the same rerun (fast sync) — both
    # the intermediate pending state and the already-resolved state are valid.
    assert view[0] in ("pending_project", "project"), f"Unexpected view after add: {view}"
    print(f"PASS: project visible instantly, state={view[0]} (interaction run: {elapsed:.0f} ms)")

    if view[0] == "pending_project":
        at = _wait_for_sync(at)
        view = at.session_state["view"]
    assert view[0] == "project" and isinstance(view[1], int), f"Pending not resolved: {view}"
    assert not _ss(at, "optimistic_projects"), "Echo should be pruned after landing"
    print("PASS: pending project resolved to real DB project", view[1])
    return at, view[1]


def test_optimistic_chat(at, project_id):
    text = f"optimistic hello {int(time.time())}"
    at.chat_input(key=f"chat_input_{project_id}").set_value(text)
    t = time.perf_counter()
    at = at.run()
    elapsed = (time.perf_counter() - t) * 1000
    assert _visible(at, text), "Chat echo should render immediately"
    print(f"PASS: chat message visible instantly (interaction run: {elapsed:.0f} ms)")

    at = _wait_for_sync(at)
    assert _visible(at, text), "Message must persist after sync"
    assert not _ss(at, f"optimistic_chat_{project_id}"), "Chat echo not pruned"
    import database as db

    assert any(m["message"] == text for m in db.get_chat(project_id)), "Message missing from DB"
    print("PASS: chat message synced to Supabase, echo pruned")
    return at


def test_optimistic_task_and_comment(at, project_id):
    import database as db

    scope = f"project_{project_id}"
    task_title = f"optimistic task {int(time.time())}"
    at.text_input(key=f"task_title_{scope}").set_value(task_title)
    t = time.perf_counter()
    at = _find_button(at, f"add_task_form_{scope}").set_value(True).run()
    elapsed = (time.perf_counter() - t) * 1000
    assert _visible(at, task_title), "Task echo should render immediately"
    print(f"PASS: new task visible instantly (interaction run: {elapsed:.0f} ms)")

    at = _wait_for_sync(at)
    tasks = db.get_tasks(project_id=project_id)
    task = next((x for x in tasks if x["title"] == task_title), None)
    assert task is not None, "Task missing from DB after sync"
    assert not _ss(at, f"optimistic_tasks_{scope}"), "Task echo not pruned"
    print("PASS: task synced to Supabase, echo pruned")

    # Toggle completion optimistically
    at.checkbox(key=f"task_done_{task['id']}").set_value(True)
    t = time.perf_counter()
    at = at.run()
    elapsed = (time.perf_counter() - t) * 1000
    assert at.checkbox(key=f"task_done_{task['id']}").value is True
    print(f"PASS: task toggle reflected instantly (interaction run: {elapsed:.0f} ms)")
    at = _wait_for_sync(at)
    fresh = next(x for x in db.get_tasks(project_id=project_id) if x["id"] == task["id"])
    assert fresh["is_done"] is True, "Toggle did not sync to DB"
    assert task["id"] not in _ss(at, "task_done_override", {}), "Override not pruned"
    print("PASS: task toggle synced to Supabase, override pruned")

    # Add a comment optimistically
    note = f"optimistic note {int(time.time())}"
    at.text_area(key=f"comment_text_{task['id']}").set_value(note)
    at = _find_button(at, f"comment_form_{task['id']}").set_value(True).run()
    assert _visible(at, note), "Comment echo should render immediately"
    at = _wait_for_sync(at)
    comments = db.get_comments_map(project_id=project_id).get(task["id"], [])
    assert any(c["content"] == note for c in comments), "Comment missing from DB after sync"
    assert not _ss(at, "optimistic_comments", {}).get(task["id"]), "Comment echo not pruned"
    print("PASS: comment visible instantly and synced to Supabase")
    return at


def test_sync_failure_is_surfaced():
    import optimistic

    def boom():
        raise RuntimeError("simulated outage")

    future = optimistic._executor().submit(boom)
    while not future.done():
        time.sleep(0.05)

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["_pending_writes"] = [{"future": future, "description": "test-operation"}]
    at = at.run()
    assert any("test-operation" in (w.value or "") for w in at.warning), (
        f"Expected failure warning, got: {[w.value for w in at.warning]}"
    )
    print("PASS: failed background sync surfaces a visible warning")


if __name__ == "__main__":
    create_temp_admin()
    _delete_temp_project()
    try:
        at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
        assert at.session_state["user"] == TEMP_ADMIN, "Login failed"
        at, project_id = test_optimistic_project_creation(at)
        at = test_optimistic_chat(at, project_id)
        at = test_optimistic_task_and_comment(at, project_id)
        test_sync_failure_is_surfaced()
    finally:
        _delete_temp_project()
        cleanup_users()
    print("\nALL OPTIMISTIC UI TESTS PASSED")
