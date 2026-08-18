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
        print("\nALL THREAD-DISCIPLINE TESTS PASSED")
    finally:
        teardown(pid)
