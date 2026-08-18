"""Verify read receipts and unread badges: DB layer, debounce, and rendering.

Run with:  python test_read_receipts.py

Covers:
  1. get_chat_unread_counts / get_task_comment_unread_counts /
     get_unread_counts_for_tasks / mark_scope_read at the DB layer.
  2. The chat-tab label badge appears when there's something unread and
     disappears once mark_scope_read has run, without breaking the
     "always default to the spec tab" behaviour fixed earlier.
  3. The task-comments expander badge, same shape.
  4. The debounce in _mark_scope_viewed: repeatedly "viewing" the same,
     unchanged set of messages must not re-dispatch a write every time —
     that's the "avoid an infinite loop of writes" requirement.
  5. The home-screen project cards' activity summary line.
"""

import time

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_read_receipts"
OTHER_USER = "temp_test_read_receipts_other"


def _cleanup():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])
    db.delete_user(OTHER_USER)


def _ss(at, key, default=None):
    return at.session_state[key] if key in at.session_state else default


def _wait_for_sync(at, seconds=8):
    deadline = time.time() + seconds
    while time.time() < deadline and _ss(at, "_pending_writes"):
        time.sleep(0.3)
    time.sleep(0.3)
    return at.run()


def _open_project(pid):
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, f"Dashboard crashed: {at.exception[0]}"
    return at


def test_urgent_and_board_queries_survive_an_attachment(pid):
    """Regression for a real crash: get_urgent_open_tasks() and _board_tasks()
    used to SELECT t.* — @st.cache_data pickles the return value, and
    psycopg2 returns bytea (attachment_data) as an unpicklable memoryview.
    A live production task with a real PDF attachment was hitting this on
    every home-screen load. Fixed by listing columns explicitly, excluding
    attachment_data (nothing here needs the bytes — only attachment_name, to
    decide whether to show anything about it at all).
    """
    db.add_task(
        "urgent task with a file", TEMP_ADMIN, TEMP_ADMIN, pid, "project",
        is_urgent=True, attachment=("doc.pdf", "application/pdf", b"%PDF-1.4 x"),
    )
    db.add_task(
        "adhoc task with a file", TEMP_ADMIN, TEMP_ADMIN, None, "urgent",
        attachment=("doc2.pdf", "application/pdf", b"%PDF-1.4 y"),
    )
    db.get_urgent_open_tasks.clear()
    db._board_tasks.clear()

    urgent = db.get_urgent_open_tasks()  # used to raise UnserializableReturnValueError
    assert any(t["title"] == "urgent task with a file" for t in urgent)
    assert all("attachment_data" not in t for t in urgent)
    print("PASS: get_urgent_open_tasks() no longer crashes on a task with an attachment")

    board = db._board_tasks("urgent")
    assert any(t["title"] == "adhoc task with a file" for t in board)
    assert all("attachment_data" not in t for t in board)
    print("PASS: _board_tasks() no longer crashes on a task with an attachment")

    db.delete_task(
        next(t["id"] for t in db._board_tasks("urgent") if t["title"] == "adhoc task with a file")
    )


def test_db_layer_counts_and_mark_read(pid):
    db.add_user(OTHER_USER, "x", "user")
    db.add_chat_message(pid, "unread 1", OTHER_USER)
    db.add_chat_message(pid, "unread 2", OTHER_USER)
    db.add_chat_message(pid, "my own, not counted", TEMP_ADMIN)

    counts = db.get_chat_unread_counts(TEMP_ADMIN)
    assert counts.get(pid, 0) == 2, f"expected 2 unread from OTHER_USER, got {counts.get(pid)}"
    print("PASS: get_chat_unread_counts excludes the viewer's own messages")

    db.mark_scope_read(TEMP_ADMIN, db.SCOPE_PROJECT_CHAT, pid)
    counts_after = db.get_chat_unread_counts(TEMP_ADMIN)
    assert counts_after.get(pid, 0) == 0
    print("PASS: mark_scope_read zeroes the chat unread count")

    db.add_task("task with comments", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "task with comments")
    db.add_comment(task["id"], "comment from other user", OTHER_USER)
    tc = db.get_task_comment_unread_counts(TEMP_ADMIN, project_id=pid)
    assert tc.get(task["id"], 0) == 1
    print("PASS: get_task_comment_unread_counts counts a teammate's comment")

    # get_unread_counts_for_tasks — the home-widget helper, an explicit id
    # list rather than one (project_id, task_type) scope.
    for_ids = db.get_unread_counts_for_tasks(TEMP_ADMIN, (task["id"],))
    assert for_ids.get(task["id"], 0) == 1
    assert db.get_unread_counts_for_tasks(TEMP_ADMIN, ()) == {}, "empty id tuple -> empty dict"
    print("PASS: get_unread_counts_for_tasks matches the scoped version for the same task")

    db.mark_scope_read(TEMP_ADMIN, db.SCOPE_TASK_COMMENTS, task["id"])
    tc_after = db.get_task_comment_unread_counts(TEMP_ADMIN, project_id=pid)
    assert tc_after.get(task["id"], 0) == 0
    print("PASS: mark_scope_read zeroes the task-comment unread count")
    return task


def test_chat_tab_badge_appears_and_clears(pid):
    db.add_chat_message(pid, "badge trigger", OTHER_USER)
    db.get_chat.clear()
    db.get_chat_watermark.clear()
    db.get_chat_unread_counts.clear()

    at = _open_project(pid)
    assert any("🔵" in (t.label or "") for t in at.tabs if "תקשורת" in (t.label or "")), (
        f"Expected a badge on the chat tab, got labels: {[t.label for t in at.tabs]}"
    )
    assert at.tabs[0].label == "📋 אפיון המוצר", "A dynamic badge must not break the default tab"
    print("PASS: chat tab shows an unread badge without breaking the spec-tab default")

    # Rendering the dashboard executes the chat fragment regardless of which
    # tab is visually selected (see _mark_scope_viewed's documented caveat),
    # so simply having rendered the page once already marks it read.
    at = at.run()
    db.get_chat_unread_counts.clear()
    at2 = _open_project(pid)
    assert not any(
        "🔵" in (t.label or "") for t in at2.tabs if "תקשורת" in (t.label or "")
    ), f"Badge should be gone after viewing, got: {[t.label for t in at2.tabs]}"
    print("PASS: chat tab badge clears after the project has been viewed")


def test_task_comment_badge_appears_and_clears(pid, task):
    db.add_comment(task["id"], "another unread comment", OTHER_USER)
    db.clear_task_caches()

    at = _open_project(pid)
    labels = [
        m.value for m in at.markdown
        if '<span class="unread-badge"' in (m.value or "")
    ]
    assert labels, "Expected an unread badge inside the task's comments expander"
    print("PASS: task comments expander shows an unread badge")

    at = at.run()
    db.get_task_comment_unread_counts.clear()
    db.get_unread_counts_for_tasks.clear()
    at2 = _open_project(pid)
    labels2 = [m.value for m in at2.markdown if '<span class="unread-badge"' in (m.value or "")]
    assert not labels2, f"Badge should be gone after viewing: {labels2}"
    print("PASS: task comments badge clears after the task board has been viewed")


def test_ping_fires_only_on_a_genuine_increase():
    """The notification ping: event-driven off a plain session_state
    comparison, not a timer — verified here by calling the comparison
    helper directly with a sequence of counts and spying on
    st.components.v1.html (the actual sound trigger)."""
    import ui_components as ui

    real_html = ui.components.html
    calls = []
    ui.components.html = lambda *a, **k: calls.append(a) or None
    try:
        import streamlit as st

        st.session_state.clear()
        key = "test_ping_scope"

        ui._play_ping_if_increased(key, 3)
        assert len(calls) == 0, "first observation of a key must stay silent (backlog, not new)"
        print("PASS: no ping on the first-ever observation of a scope")

        ui._play_ping_if_increased(key, 3)
        assert len(calls) == 0, "an unchanged count must not ping"
        print("PASS: no ping when the count is unchanged")

        ui._play_ping_if_increased(key, 1)
        assert len(calls) == 0, "a decrease (a read happening) must not ping"
        print("PASS: no ping on a decrease")

        ui._play_ping_if_increased(key, 4)
        assert len(calls) == 1, f"a genuine increase must ping exactly once, got {len(calls)}"
        print("PASS: exactly one ping on a genuine increase")

        ui._play_ping_if_increased(key, 4)
        assert len(calls) == 1, "the same count again must not re-ping"
        print("PASS: no repeat ping while the count stays at the new level")
    finally:
        ui.components.html = real_html


def test_debounce_does_not_rewrite_on_every_tick(pid):
    """The core "no infinite loop of writes" requirement: viewing the SAME
    unchanged messages repeatedly must dispatch mark_scope_read exactly once,
    not once per fragment poll tick.

    Spies on optimistic.submit_write (the dispatch call), not db.mark_scope_read
    itself — the debounce decision (dispatch or skip) is made synchronously
    inside _mark_scope_viewed, but the actual write only runs later on a
    background worker thread, so asserting on the worker-side call is an
    inherent race against that thread actually getting scheduled.
    """
    import optimistic
    import ui_components as ui

    real_submit = optimistic.submit_write
    dispatches = []
    optimistic.submit_write = lambda *a, **k: dispatches.append(a) or real_submit(*a, **k)
    try:
        import streamlit as st

        st.session_state.clear()
        st.session_state["user"] = TEMP_ADMIN
        messages = [{"created_at": "2026-01-01T00:00:00"}]
        for _ in range(5):
            ui._mark_scope_viewed(db.SCOPE_PROJECT_CHAT, pid, messages)
        assert len(dispatches) == 1, f"expected exactly 1 dispatched write, got {len(dispatches)}"
        print("PASS: 5 identical 'views' in a row dispatch exactly 1 write, not 5")

        # A genuinely new message must still be marked read.
        newer = messages + [{"created_at": "2026-01-01T00:00:05"}]
        ui._mark_scope_viewed(db.SCOPE_PROJECT_CHAT, pid, newer)
        assert len(dispatches) == 2, "a real change must still trigger a write"
        print("PASS: a new message still triggers exactly one more write")
    finally:
        optimistic.submit_write = real_submit
        # Give the two dispatched background writes a moment to actually run
        # before the next test reads the same rows.
        deadline = time.time() + 5
        while time.time() < deadline and _ss(st, "_pending_writes"):
            time.sleep(0.2)


def test_home_screen_activity_summary(pid):
    db.add_chat_message(pid, "for the home screen badge", OTHER_USER)
    db.add_task("open task for counts", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    db.clear_task_caches()
    db.get_chat_unread_counts.clear()

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = None
    at = at.run()
    assert not at.exception, f"Home screen crashed: {at.exception[0]}"

    activity = [
        m.value for m in at.markdown if '<div class="project-activity-line"' in (m.value or "")
    ]
    this_project = [b for b in activity if "הודעות חדשות" in b or "משימות פתוחות" in b]
    assert this_project, f"Expected an activity line, got: {activity}"
    print("PASS: home screen shows the project activity summary line")


def test_home_fragment_updates_live_without_navigation(pid):
    """The home screen used to refresh unread badges / the activity line /
    the urgent widget / the ping only on a full navigation-triggered rerun.
    It's now wrapped in @st.fragment(run_every=HOME_POLL), so the browser's
    own poll timer reruns just this fragment every couple of seconds.
    Standing in for that here: rerun the SAME AppTest session without
    touching session_state["view"] at all, and confirm a change made in
    between shows up — no navigation, and no new polling loop was added to
    produce it."""
    import ui_components as ui

    real_html = ui.components.html
    calls = []
    ui.components.html = lambda *a, **k: calls.append(a) or None
    try:
        at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
        at.session_state["view"] = None
        at = at.run()
        assert not at.exception, f"Home screen crashed: {at.exception[0]}"

        db.add_chat_message(pid, "arrived while on the home screen", OTHER_USER)
        db.get_chat_unread_counts.clear()

        at = at.run()  # stands in for the fragment's own run_every rerun
        assert not at.exception, f"Home screen re-render crashed: {at.exception[0]}"
        activity = [
            m.value for m in at.markdown if '<div class="project-activity-line"' in (m.value or "")
        ]
        assert any("הודעות חדשות" in a for a in activity), (
            f"Expected the new unread message to show up with no navigation, got: {activity}"
        )
        assert len(calls) >= 1, "expected the ping to fire on the same rerun that surfaces the new unread count"
        print("PASS: home screen picks up a new unread message and pings on its own, without navigating away")
    finally:
        ui.components.html = real_html


def test_task_list_header_row_aligns_with_cards(pid):
    """6 header columns must match _render_task's 6 columns exactly."""
    import ui_components as ui

    at = _open_project(pid)
    headers = [m.value for m in at.markdown if '<div class="task-col-header"' in (m.value or "")]
    assert len(headers) == len(ui.TASK_ROW_HEADERS) == 6, (
        f"expected {len(ui.TASK_ROW_HEADERS)} header cells, got {len(headers)}"
    )
    for label in ui.TASK_ROW_HEADERS:
        assert any(label in (h or "") for h in headers), f"missing header: {label}"
    print("PASS: the 6-column header row matches _render_task's column layout")


if __name__ == "__main__":
    create_temp_admin()
    _cleanup()
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    try:
        test_urgent_and_board_queries_survive_an_attachment(pid)
        task = test_db_layer_counts_and_mark_read(pid)
        test_chat_tab_badge_appears_and_clears(pid)
        test_task_comment_badge_appears_and_clears(pid, task)
        test_debounce_does_not_rewrite_on_every_tick(pid)
        test_ping_fires_only_on_a_genuine_increase()
        test_home_screen_activity_summary(pid)
        test_home_fragment_updates_live_without_navigation(pid)
        test_task_list_header_row_aligns_with_cards(pid)
        print("\nALL READ-RECEIPT TESTS PASSED")
    finally:
        _cleanup()
