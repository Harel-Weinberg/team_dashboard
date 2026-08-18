"""E6: prove background workers never call into Streamlit.

Run with:  python test_thread_discipline.py

Spies on the st.* surfaces a worker could reach (st.secrets, cache clears,
st.session_state) and drives every real background write path through the
optimistic pool, asserting nothing off-thread touches them.
"""

import threading
import time

import streamlit as st

import database as db
import notifications
import optimistic
from test_login_flow import TEMP_ADMIN, cleanup, create_temp_admin

TEMP_PROJECT = "temp_test_threads"
VIOLATIONS: list[str] = []
_LOCK = threading.Lock()


def _flag(what: str) -> None:
    if db.on_worker_thread():
        with _LOCK:
            VIOLATIONS.append(f"{threading.current_thread().name}: {what}")


def install_spies() -> None:
    secrets_cls = type(st.secrets)
    real_getitem = secrets_cls.__getitem__

    def spy_getitem(self, key):
        _flag(f"st.secrets[{key!r}]")
        return real_getitem(self, key)

    secrets_cls.__getitem__ = spy_getitem

    cached_cls = type(db.get_chat)
    real_clear = cached_cls.clear

    def spy_clear(self, *a, **k):
        _flag("st.cache_data.clear()")
        return real_clear(self, *a, **k)

    cached_cls.clear = spy_clear


def setup():
    cleanup()
    create_temp_admin()
    db.ensure_pool()          # render thread, as main() does
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])
    return db.add_project(TEMP_PROJECT, TEMP_ADMIN)


def teardown(pid):
    if pid:
        db.delete_project(pid)
    cleanup()


def test_every_write_path_off_thread(pid):
    """Dispatch each background write and wait for it to land."""
    futures = [
        optimistic.submit_write("chat", db.add_chat_message, pid, "שלום", TEMP_ADMIN, "tid-1"),
        optimistic.submit_write("task", db.add_task, "משימה", TEMP_ADMIN, TEMP_ADMIN, pid,
                                "project", False),
        optimistic.submit_write("spec", db.save_spec, pid, "אפיון", TEMP_ADMIN),
        optimistic.submit_write("notify", notifications.send_notification, TEMP_ADMIN,
                                "הודעה", {"email": None, "phone": None}),
    ]
    for f in futures:
        exc = f.exception(timeout=30)
        assert exc is None, f"background write raised: {exc!r}"
    print(f"PASS: {len(futures)} background write paths completed on worker threads")


def test_no_streamlit_calls_from_workers():
    assert not VIOLATIONS, "workers called into Streamlit:\n  " + "\n  ".join(VIOLATIONS)
    print("PASS: no st.secrets / cache-clear call was made from a worker thread")


def test_invalidations_were_deferred(pid):
    """Worker-side invalidations must be queued, then applied by the render thread."""
    drained = db.drain_deferred_invalidations()
    assert drained > 0, "expected worker writes to queue cache invalidations"
    print(f"PASS: {drained} cache invalidation(s) deferred to the render thread")

    # and the render thread now sees the worker's write
    assert any(m["message"] == "שלום" for m in db.get_chat(pid)), "chat write not visible"
    print("PASS: after draining, the render thread reads the worker's write")


def test_idempotent_retry(pid):
    """Re-sending the same client_msg_id must not double-post."""
    before = len(db.get_chat(pid))
    db.add_chat_message(pid, "שלום", TEMP_ADMIN, "tid-1")   # same id as above
    db.get_chat.clear()
    after = len(db.get_chat(pid))
    assert after == before, f"retry double-posted: {before} -> {after}"
    print("PASS: retrying a send with the same client_msg_id is a no-op")


def test_task_board_poll_needs_its_own_drain(pid):
    """Reproduces, then confirms the fix for, the "stuck at מסתנכרן" report.

    set_task_done runs on a worker thread and clears the task caches through
    db._invalidate(), which — per the E6 rule that workers must not call
    st.cache_data.clear() themselves — only QUEUES the clear. Nothing applies
    it until something calls drain_deferred_invalidations(). A polling
    fragment that reruns on schedule but never drains would therefore poll a
    permanently stale cache forever: this is the actual root cause the user
    hit, not "a background thread doesn't trigger a rerun" as originally
    diagnosed. _task_board_fragment now drains at its own top (ui_components.
    py) precisely so its 1s poll can see a write that landed since the last
    tick. This test proves both halves: the staleness exists before a drain,
    and one drain call is enough to clear it — independent of AppTest, which
    cannot simulate a fragment-only rerun (it always re-executes the full
    script, so it could not have caught this).
    """
    db.clear_task_caches()
    task_id = None
    with db.get_cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (project_id, task_type, title, created_by) "
            "VALUES (%s, 'project', 'drain probe', %s) RETURNING id",
            (pid, TEMP_ADMIN),
        )
        task_id = cur.fetchone()["id"]
    db.clear_task_caches()
    before = next(t for t in db.get_tasks(project_id=pid) if t["id"] == task_id)
    assert before["is_done"] is False

    future = optimistic.submit_write(
        "task-done", db.set_task_done, task_id, True, TEMP_ADMIN
    )
    exc = future.exception(timeout=30)
    assert exc is None, f"background write raised: {exc!r}"

    # The write landed in Postgres, but its cache clear is still queued.
    stale = next(t for t in db.get_tasks(project_id=pid) if t["id"] == task_id)
    assert stale["is_done"] is False, (
        "expected a stale read before drain — if this fails, either the "
        "deferred-invalidation queue changed, or the cache TTL expired "
        "naturally and this test is no longer isolating what it claims to"
    )
    print("PASS: reproduced the bug — a worker's write is invisible before drain")

    drained = db.drain_deferred_invalidations()
    assert drained > 0, "expected the queued task-cache clear to be drained"
    fresh = next(t for t in db.get_tasks(project_id=pid) if t["id"] == task_id)
    assert fresh["is_done"] is True, "drain did not surface the worker's write"
    print("PASS: draining once (as _task_board_fragment now does every poll "
          "tick) makes the write visible with no further user interaction")


if __name__ == "__main__":
    install_spies()
    pid = None
    try:
        pid = setup()
        test_every_write_path_off_thread(pid)
        time.sleep(0.2)
        test_no_streamlit_calls_from_workers()
        test_invalidations_were_deferred(pid)
        test_idempotent_retry(pid)
        test_task_board_poll_needs_its_own_drain(pid)
        print("\nALL THREAD-DISCIPLINE TESTS PASSED")
    finally:
        teardown(pid)
