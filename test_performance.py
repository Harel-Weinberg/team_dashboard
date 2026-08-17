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

    assert [m["message"] for m in bundle["chat"]] == ["הודעה ראשונה"]
    assert isinstance(bundle["chat"][0]["created_at"], datetime)
    print("PASS: bundle returns project+spec+tasks+comments+chat correctly, timestamps revived")


def test_warm_then_zero_db_access(pid, task):
    """After warm_project, every UI-style read must be served purely from cache."""
    db.clear_task_caches()
    db.warm_project(pid, wait=True)

    real_pool = db._get_pool
    db._get_pool = lambda: (_ for _ in ()).throw(RuntimeError("unexpected DB access"))
    try:
        assert db.get_project(pid)["name"] == TEMP_PROJECT
        assert db.get_spec(pid)["content"] == "תוכן אפיון"
        assert len(db.get_tasks(project_id=pid, task_type="project")) == 2
        assert task["id"] in db.get_comments_map(project_id=pid, task_type="project")
        assert len(db.get_chat(pid)) == 1
        db.get_contacts()
        db.get_users()
    finally:
        db._get_pool = real_pool
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


if __name__ == "__main__":
    pid, task = _seed()
    try:
        test_bundle_matches_reality(pid, task)
        test_warm_then_zero_db_access(pid, task)
        test_writes_never_serve_stale_data(pid, task)
        test_board_dispatch()
        test_prefetch_is_nonblocking(pid)
    finally:
        _cleanup()
    print("\nALL PERFORMANCE TESTS PASSED")
