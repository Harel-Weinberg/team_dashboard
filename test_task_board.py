"""Verify the task-board revamp: rich fields, filters, and comment bubbles.

Run with:  python test_task_board.py

Split out from test_urgent_tasks.py / test_optimistic.py (which already
cover the status dropdown's optimistic round-trip and rerun-loop safety) —
this file is about the surface that's new: description/due_date/tags/
attachment on a task, the search/status/assignee filter bar, and reusing the
chat bubble markup for task comments.
"""

import time

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_task_board"
OTHER_USER = "temp_test_task_board_other"


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


def _find_by_id_substring(at, needle):
    """st.download_button has no dedicated AppTest accessor (no at.download_button
    property in this Streamlit version) -- walk the raw element tree instead."""
    def flatten(node, out):
        out.append(node)
        for child in (getattr(node, "children", None) or {}).values():
            flatten(child, out)

    order = []
    flatten(at.main, order)
    return [n for n in order if needle in getattr(getattr(n, "proto", None), "id", "")]


def _open_project(pid):
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, f"Dashboard crashed: {at.exception[0]}"
    return at


def test_migration_is_idempotent_and_additive():
    """init_db()'s task-board migrations must survive being re-run, and must
    never touch is_done -- the boolean stays the internal source of truth."""
    with db.get_cursor() as cur:
        cur.execute(db._SCHEMA)
        cur.execute(db._MIGRATIONS)
        cur.execute(db._INDEXES)
        cur.execute(db._SCHEMA)
        cur.execute(db._MIGRATIONS)
        cur.execute(db._INDEXES)
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'"
        )
        columns = {r["column_name"] for r in cur.fetchall()}
    for col in ("status", "description", "due_date", "tags",
                "attachment_name", "attachment_type", "attachment_data", "is_done"):
        assert col in columns, f"missing column: {col}"
    print("PASS: schema migration is idempotent and additive")


def test_add_task_form_is_collapsed_inside_an_expander(pid):
    """The add-task form must be collapsed by default, inside a real
    st.expander (not just visually hidden) — Expander.proto has no
    at.expander(key=...) accessor in this Streamlit version (Expander only
    stores the stripped-down Expandable submessage, which has no populated
    id field), so this matches on the label instead."""
    at = _open_project(pid)
    matches = [e for e in at.expander if e.label == "➕ הוספת משימה חדשה"]
    assert len(matches) == 1, f"expected exactly one add-task expander, found {len(matches)}"
    assert matches[0].proto.expanded is False, "the add-task form must start collapsed"
    print("PASS: the add-task form is wrapped in a collapsed-by-default expander")


def test_form_creates_a_fully_populated_task(pid):
    from datetime import date

    at = _open_project(pid)
    scope = f"project_{pid}"
    title = f"משימה מפורטת {int(time.time())}"

    at.text_input(key=f"task_title_{scope}").set_value(title)
    at.text_area(key=f"task_description_{scope}").set_value("תיאור מפורט של המשימה")
    at.selectbox(key=f"task_assignee_{scope}").set_value(TEMP_ADMIN)
    at.date_input(key=f"task_due_{scope}").set_value(date(2026, 12, 31))
    at.multiselect(key=f"task_tags_{scope}").set_value(["Bug", "Front-End"])
    submit = next(b for b in at.button if b.key == f"add_task_submit_{scope}")
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"
    at = _wait_for_sync(at)

    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == title)
    assert task["description"] == "תיאור מפורט של המשימה"
    assert task["due_date"] == date(2026, 12, 31)
    assert sorted(task["tags"]) == ["Bug", "Front-End"]
    assert task["status"] == db.STATUS_IN_PROGRESS
    print("PASS: form-created task persists description, due date and tags")

    # And they render: tag pills + description + due date all reach the DOM.
    html_blocks = [m.value or "" for m in at.markdown if title in (m.value or "")]
    assert html_blocks, "Task title not rendered"
    assert "task-tag" in html_blocks[0], "Tag pills missing from the rendered title line"
    assert (
        any("תיאור מפורט" in (c.value or "") for c in at.caption)
        or any("תיאור מפורט" in (m.value or "") for m in at.markdown)
    ), "Description not shown on the card"
    assert any("31/12/2026" in (c.value or "") for c in at.caption), (
        "Due date not shown on the card"
    )
    print("PASS: tags, description and due date are all rendered on the card")
    return task


def test_attachment_round_trips_and_download_button_renders(pid):
    # Below the cap: stored and downloadable.
    small = b"%PDF-1.4 small file"
    db.add_task(
        "משימה עם קובץ", TEMP_ADMIN, TEMP_ADMIN, pid, "project",
        attachment=("doc.pdf", "application/pdf", small),
    )
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "משימה עם קובץ")
    assert "attachment_data" not in task, "the heavy blob must not ride along in the bundle"
    fetched = db.get_task_attachment(task["id"])
    assert fetched == ("doc.pdf", "application/pdf", small)
    print("PASS: a small attachment round-trips and is excluded from the task bundle")

    at = _open_project(pid)
    dl_nodes = _find_by_id_substring(at, f"task_attachment_dl_{task['id']}")
    assert dl_nodes and dl_nodes[0].type == "download_button", (
        "Download button missing for a task with an attachment"
    )
    print("PASS: the download button renders for a task that has an attachment")


def test_form_upload_success_and_oversized_rejection(pid):
    """Drives the real add_task_form file_uploader widget, not a stand-in."""
    import ui_components as ui

    at = _open_project(pid)
    scope = f"project_{pid}"

    small_title = f"קובץ קטן {int(time.time())}"
    at.text_input(key=f"task_title_{scope}").set_value(small_title)
    at.file_uploader(key=f"task_attachment_{scope}").set_value(
        ("small.pdf", b"%PDF-1.4 ok", "application/pdf")
    )
    submit = next(b for b in at.button if b.key == f"add_task_submit_{scope}")
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"
    at = _wait_for_sync(at)

    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == small_title)
    assert task["attachment_name"] == "small.pdf"
    fetched = db.get_task_attachment(task["id"])
    assert fetched == ("small.pdf", "application/pdf", b"%PDF-1.4 ok")
    print("PASS: an attachment uploaded through the real form widget is saved and fetchable")

    at = _open_project(pid)
    big_title = f"קובץ גדול מדי {int(time.time())}"
    at.text_input(key=f"task_title_{scope}").set_value(big_title)
    at.file_uploader(key=f"task_attachment_{scope}").set_value(
        ("huge.pdf", b"x" * (ui.MAX_ATTACHMENT_BYTES + 1), "application/pdf")
    )
    submit = next(b for b in at.button if b.key == f"add_task_submit_{scope}")
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"
    assert any(
        "גדול" in (e.value or "") for e in at.error
    ), "An oversized upload must surface a clear error"
    at = _wait_for_sync(at)

    created = next((t for t in db.get_tasks(project_id=pid) if t["title"] == big_title), None)
    assert created is not None, "The task itself should still be created"
    assert created["attachment_name"] is None, (
        "An oversized upload must be dropped, not silently truncated and stored"
    )
    assert db.get_task_attachment(created["id"]) is None
    print("PASS: an oversized upload is rejected with an error; the task is created without it")


def _visible_titles_text(at):
    return " ".join(m.value or "" for m in at.markdown)


def test_filters_narrow_the_visible_list(pid):
    db.add_user(OTHER_USER, "x", "user")
    db.add_task("משימה של אחר", OTHER_USER, TEMP_ADMIN, pid, "project")
    my_title = f"המשימה שלי {int(time.time())}"
    db.add_task(my_title, TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    db.clear_task_caches()

    at = _open_project(pid)
    scope = f"project_{pid}"

    text = _visible_titles_text(at)
    assert my_title in text and "משימה של אחר" in text, (
        "Both tasks should be visible with no filter applied"
    )

    at.toggle(key=f"task_mine_{scope}").set_value(True)
    at = at.run()
    text = _visible_titles_text(at)
    assert my_title in text, "My own task must stay visible"
    assert "משימה של אחר" not in text, "'המשימות שלי' must hide tasks assigned to someone else"
    print("PASS: 'המשימות שלי' toggle filters by assignee")
    at.toggle(key=f"task_mine_{scope}").set_value(False)
    at = at.run()

    at.text_input(key=f"task_search_{scope}").set_value("של אחר")
    at = at.run()
    text = _visible_titles_text(at)
    assert "משימה של אחר" in text
    assert my_title not in text, "Search must narrow to matching titles"
    print("PASS: search bar filters by title/description")
    at.text_input(key=f"task_search_{scope}").set_value("")
    at = at.run()

    status_filter = next(m for m in at.multiselect if m.key == f"task_status_filter_{scope}")
    at = status_filter.set_value([db.STATUS_DONE]).run()
    text = _visible_titles_text(at)
    assert my_title not in text, "Filtering to only בוצע must hide an open task"
    print("PASS: status multiselect filters by status")


def test_comments_render_as_chat_bubbles(pid, task):
    import ui_components as ui

    at = _open_project(pid)
    note = f"הערה לבדיקה {int(time.time())}"
    at.text_area(key=f"comment_text_{task['id']}").set_value(note)
    submit = next(
        b for b in at.button
        if b.key and b.key.startswith("FormSubmitter:") and f"comment_form_{task['id']}" in b.key
    )
    at = submit.set_value(True).run()
    assert not at.exception, f"Comment submit crashed: {at.exception[0]}"

    pending_html = next(
        (m.value for m in at.markdown
         if '<div class="chat-row' in (m.value or "") and note in m.value),
        None,
    )
    assert pending_html is not None, "Pending comment must render with the chat-bubble markup"
    print("PASS: a pending comment renders with the same bubble markup as project chat")

    at = _wait_for_sync(at)
    comments = db.get_comments_map(project_id=pid).get(task["id"], [])
    assert any(c["content"] == note for c in comments), "Comment missing from DB after sync"
    landed_html = next(
        (m.value for m in at.markdown
         if '<div class="chat-row' in (m.value or "") and note in m.value),
        None,
    )
    assert landed_html is not None
    print("PASS: the landed comment also renders as a bubble")

    # Sanity: _chat_bubble_html is literally the same function chat uses.
    rendered = ui._chat_bubble_html("Harel", "01/01/2026 00:00", "בדיקה", is_mine=True)
    assert 'class="chat-row mine"' in rendered
    print("PASS: task comments reuse ui_components._chat_bubble_html directly")


if __name__ == "__main__":
    create_temp_admin()
    _cleanup()
    test_migration_is_idempotent_and_additive()
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    try:
        test_add_task_form_is_collapsed_inside_an_expander(pid)
        task = test_form_creates_a_fully_populated_task(pid)
        test_attachment_round_trips_and_download_button_renders(pid)
        test_form_upload_success_and_oversized_rejection(pid)
        test_filters_narrow_the_visible_list(pid)
        test_comments_render_as_chat_bubbles(pid, task)
        print("\nALL TASK BOARD TESTS PASSED")
    finally:
        _cleanup()
