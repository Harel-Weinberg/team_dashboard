"""Verify the navigation-performance layer: bundle correctness, cache warming,
and — critically — that no write path serves stale data afterwards.

Run with:  python test_performance.py
"""

from datetime import datetime

import database as db
from test_login_flow import TEMP_ADMIN, cleanup, create_temp_admin

TEMP_PROJECT = "temp_test_perf_project"


def _cleanup():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])
    cleanup()


def _seed():
    _cleanup()
    create_temp_admin()
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    db.add_task("משימה ראשונה", TEMP_ADMIN, TEMP_ADMIN, pid, "project", is_urgent=True)
    db.add_task("משימה שנייה", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    task = db.get_tasks(project_id=pid)[0]
    db.add_comment(task["id"], "הערה ראשונה", TEMP_ADMIN)
    db.add_chat_message(pid, "הודעה ראשונה", TEMP_ADMIN)
    db.save_spec(pid, "תוכן אפיון", TEMP_ADMIN)
    return pid, task


def test_bundle_matches_reality(pid, task):
    """The one-round-trip bundle must return exactly what direct SQL returns."""
    bundle = db._project_bundle(pid)

    assert bundle["project"]["name"] == TEMP_PROJECT
    assert isinstance(bundle["project"]["created_at"], datetime), "timestamps must be revived"
    assert bundle["spec"]["content"] == "תוכן אפיון"
    assert bundle["spec"]["updated_by"] == TEMP_ADMIN

    titles = [t["title"] for t in bundle["tasks"]]
    assert titles == ["משימה ראשונה", "משימה שנייה"], f"Wrong tasks/order: {titles}"
    assert bundle["tasks"][0]["is_urgent"] is True and bundle["tasks"][0]["is_done"] is False
    assert isinstance(bundle["tasks"][0]["created_at"], datetime)

    comments = bundle["comments_map"][task["id"]]
    assert [c["content"] for c in comments] == ["הערה ראשונה"]
    assert isinstance(comments[0]["created_at"], datetime)

    # Chat is no longer part of the bundle — it has its own short-TTL loader so
    # the 3s chat fragment can poll it without dragging the rest of the page down.
    assert "chat" not in bundle
    chat = db.get_chat(pid)
    assert [m["message"] for m in chat] == ["הודעה ראשונה"]
    assert isinstance(chat[0]["created_at"], datetime)
    print("PASS: bundle returns project+spec+tasks+comments+chat correctly, timestamps revived")


def test_warm_then_zero_db_access(pid, task):
    """After warm_project, every UI-style read must be served purely from cache."""
    db.clear_task_caches()
    db.warm_project(pid, wait=True)

    # Gate every route to the database, not just the pool factory: get_cursor()
    # now borrows from a plain module global (see the thread-discipline notes in
    # database.py), so patching the pool constructor would no longer intercept.
    real_cursor = db.get_cursor

    def _no_db(*_args, **_kwargs):
        raise RuntimeError("unexpected DB access")

    db.get_cursor = _no_db
    try:
        assert db.get_project(pid)["name"] == TEMP_PROJECT
        assert db.get_spec(pid)["content"] == "תוכן אפיון"
        assert len(db.get_tasks(project_id=pid, task_type="project")) == 2
        assert task["id"] in db.get_comments_map(project_id=pid, task_type="project")
        assert len(db.get_chat(pid)) == 1
        db.get_contacts()
        db.get_users()
    finally:
        db.get_cursor = real_cursor
    print("PASS: after warm_project, the full dashboard renders with ZERO DB round-trips")


def test_writes_never_serve_stale_data(pid, task):
    """Every write must invalidate the bundle so the next read is fresh."""
    db.warm_project(pid, wait=True)  # make sure everything is cached first

    db.add_task("משימה שלישית", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    assert any(t["title"] == "משימה שלישית" for t in db.get_tasks(project_id=pid)), "stale tasks"

    db.set_task_done(task["id"], True, TEMP_ADMIN)
    assert next(t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"])["is_done"], (
        "stale is_done"
    )
    db.set_task_urgent(task["id"], False)
    assert not next(
        t for t in db.get_tasks(project_id=pid) if t["id"] == task["id"]
    )["is_urgent"], "stale is_urgent"

    db.add_comment(task["id"], "הערה שנייה", TEMP_ADMIN)
    assert len(db.get_comments_map(project_id=pid)[task["id"]]) == 2, "stale comments"

    db.add_chat_message(pid, "הודעה שנייה", TEMP_ADMIN)
    assert len(db.get_chat(pid)) == 2, "stale chat"

    db.save_spec(pid, "תוכן חדש", TEMP_ADMIN)
    assert db.get_spec(pid)["content"] == "תוכן חדש", "stale spec"

    assert not any(
        t["id"] == task["id"] for t in db.get_urgent_open_tasks()
    ), "stale urgent widget"
    print("PASS: all six write paths invalidate the bundle — no stale reads anywhere")


def test_board_dispatch():
    """The global boards (no project) still work through the dispatchers."""
    tasks = db.get_tasks(project_id=None, task_type="urgent")
    comments = db.get_comments_map(project_id=None, task_type="urgent")
    assert isinstance(tasks, list) and isinstance(comments, dict)
    assert all(t["project_id"] is None for t in tasks)
    print("PASS: global urgent/backlog boards dispatch to their own cached queries")


def test_prefetch_is_nonblocking(pid):
    import time

    db.clear_task_caches()
    t = time.perf_counter()
    db.prefetch_all_projects()
    elapsed = (time.perf_counter() - t) * 1000
    assert elapsed < 200, f"prefetch_all_projects must not block the UI ({elapsed:.0f} ms)"
    print(f"PASS: home-screen prefetch is fire-and-forget ({elapsed:.0f} ms to enqueue)")


def test_chat_watermark_shortcircuits_full_fetch(pid):
    """The full get_chat() query must only run again once the watermark moves.

    ui_components._watermarked_messages() is what the 500ms chat fragment
    calls every tick; this proves an idle chat costs repeated cheap MAX()
    probes but NOT repeated full SELECT * fetches, and that a real new
    message is still detected on the very next tick.
    """
    import streamlit as st
    import ui_components as ui

    for key in ("chat_watermark_seen", "chat_last_messages"):
        st.session_state.pop(key, None)
    db.get_chat.clear()
    db.get_chat_watermark.clear()

    real_get_chat = db.get_chat
    calls = []

    def counting_get_chat(project_id, limit=db.CHAT_PAGE):
        calls.append(project_id)
        return real_get_chat(project_id, limit)

    counting_get_chat.clear = real_get_chat.clear  # add_chat_message calls get_chat.clear()
    db.get_chat = counting_get_chat
    try:
        ui._watermarked_messages(pid)
        ui._watermarked_messages(pid)  # nothing changed since the first call
        assert len(calls) == 1, f"expected 1 full fetch across 2 unchanged ticks, got {len(calls)}"

        db.add_chat_message(pid, "watermark probe", TEMP_ADMIN)
        third = ui._watermarked_messages(pid)
        assert len(calls) == 2, "a real new message must trigger exactly one more full fetch"
        assert any(m["message"] == "watermark probe" for m in third), "new message not returned"
    finally:
        db.get_chat = real_get_chat
        db.get_chat.clear()
        db.get_chat_watermark.clear()
        for key in ("chat_watermark_seen", "chat_last_messages"):
            st.session_state.pop(key, None)
    print("PASS: watermark short-circuits redundant full fetches, still detects real changes")


if __name__ == "__main__":
    pid, task = _seed()
    try:
        test_bundle_matches_reality(pid, task)
        test_warm_then_zero_db_access(pid, task)
        test_writes_never_serve_stale_data(pid, task)
        test_board_dispatch()
        test_prefetch_is_nonblocking(pid)
        test_chat_watermark_shortcircuits_full_fetch(pid)
    finally:
        _cleanup()
    print("\nALL PERFORMANCE TESTS PASSED")
