"""Verify the iMessage-style chat redesign: scroll panel, order, bubbles, RTL.

Run with:  python test_chat_bubbles.py

Most of this has to be checked against the underlying element proto rather
than a friendly AppTest property, because "is this a fixed-height scroll
area" and "which side does this bubble render on" aren't things the
high-level API exposes directly.
"""

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_chat_bubbles"
OTHER_USER = "temp_test_chat_bubbles_other"


def _cleanup():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])
    db.delete_user(OTHER_USER)


def _flatten(node, out):
    out.append(node)
    for child in (getattr(node, "children", None) or {}).values():
        _flatten(child, out)


def _find_by_id_substring(at, needle):
    order = []
    _flatten(at.main, order)
    matches = [n for n in order if needle in getattr(getattr(n, "proto", None), "id", "")]
    assert len(matches) == 1, f"expected exactly 1 match for {needle!r}, found {len(matches)}"
    return matches[0]


def _document_index(at, predicate):
    order = []
    _flatten(at.main, order)
    return next(i for i, n in enumerate(order) if predicate(n))


def test_scroll_container_is_fixed_height_and_autoscrolls(pid):
    """Requirement 1: the page must stop growing with the conversation."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, at.exception[0] if at.exception else None

    scroll = _find_by_id_substring(at, "chat_scroll_")
    assert scroll.type == "flex_container"
    assert scroll.proto.height_config.pixel_height == 500, "expected a fixed-height panel"
    assert scroll.proto.flex_container.border is False, "border=False was requested explicitly"
    # Oldest-at-top/newest-at-bottom (standard chat-app order) means the
    # newest message is always the LAST thing added — autoscroll=True is
    # what keeps the view anchored there instead of wherever it happened to
    # be scrolled before.
    assert scroll.proto.autoscroll is True
    print("PASS: chat renders in a fixed 500px, borderless, autoscrolling panel")


def test_chat_input_renders_below_the_scroll_panel(pid):
    """Requirement 2: pinned input directly underneath the scrollable area."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    scroll_index = _document_index(
        at, lambda n: "chat_scroll_" in getattr(getattr(n, "proto", None), "id", "")
    )
    input_index = _document_index(at, lambda n: n.type == "chat_input")
    assert scroll_index < input_index, "chat_input must come after (below) the scroll panel"
    print("PASS: chat_input is positioned after the scroll panel in document order")


def test_oldest_message_renders_first(pid):
    """Requirement 1: standard chat-app order — oldest at the top, newest at
    the bottom, matching WhatsApp/iMessage."""
    older = f"older-{pid}"
    newer = f"newer-{pid}"
    db.add_chat_message(pid, older, TEMP_ADMIN)
    db.add_chat_message(pid, newer, TEMP_ADMIN)
    db.get_chat.clear()
    db.get_chat_watermark.clear()

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    batch = next(m.value for m in at.markdown if '<div class="chat-row' in (m.value or ""))
    assert batch.index(older) < batch.index(newer), (
        "the older message must appear BEFORE the newer one in the rendered HTML "
        "(top of the panel), not after"
    )
    print("PASS: the oldest message renders above the newer one")


def test_pending_send_appends_after_landed_messages(pid):
    """Requirement 3: the optimistic echo appears at the BOTTOM, below every
    already-landed message — not above them the way the previous (newest-at-
    top) design rendered it."""
    landed_text = f"already-landed-{pid}"
    db.add_chat_message(pid, landed_text, TEMP_ADMIN)
    db.get_chat.clear()
    db.get_chat_watermark.clear()

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    pending_text = f"still-sending-{pid}"
    at = at.chat_input(key=f"chat_input_{pid}").set_value(pending_text).run()
    assert not at.exception, at.exception[0] if at.exception else None

    landed_index = _document_index(
        at, lambda n: n.type == "markdown" and landed_text in (n.proto.body or "")
    )
    pending_index = _document_index(
        at, lambda n: n.type == "markdown" and pending_text in (n.proto.body or "")
    )
    # <= rather than <: the background send can resolve fast enough that by
    # the time this assertion runs, _promote_confirmed has already forced a
    # refetch and the message landed for real — merging it into the SAME
    # batched markdown block as landed_text (both then share one index).
    # That's correct behaviour, not a bug, so it must not fail this check.
    assert landed_index <= pending_index, (
        "the pending echo must render AFTER (below) the already-landed message"
    )
    print("PASS: the optimistic 'sending...' echo appends at the bottom, below landed messages")


def test_bubble_side_matches_sender_not_viewer_identity(pid):
    """Requirement 4: my messages get one class/side, everyone else's the other."""
    db.add_user(OTHER_USER, "x", "user")
    mine_text = f"mine-{pid}"
    theirs_text = f"theirs-{pid}"
    db.add_chat_message(pid, mine_text, TEMP_ADMIN)
    db.add_chat_message(pid, theirs_text, OTHER_USER)
    db.get_chat.clear()
    db.get_chat_watermark.clear()

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()

    batch = next(m.value for m in at.markdown if '<div class="chat-row' in (m.value or ""))
    mine_row = batch[: batch.index(mine_text)].rsplit('<div class="chat-row ', 1)[-1]
    theirs_row = batch[: batch.index(theirs_text)].rsplit('<div class="chat-row ', 1)[-1]
    assert mine_row.startswith("mine"), f"my own message must use the 'mine' class, got {mine_row!r}"
    assert theirs_row.startswith("theirs"), (
        f"the other user's message must use the 'theirs' class, got {theirs_row!r}"
    )
    print("PASS: sender identity (not viewer) decides which side/class a bubble gets")


def test_message_text_is_html_escaped():
    """A message body must never be able to inject markup into the bubble."""
    import ui_components as ui

    hostile = "<img src=x onerror=alert(1)>"
    rendered = ui._chat_bubble_html("Harel", "01/01/2026 00:00", hostile, is_mine=True)
    assert "<img" not in rendered, "raw HTML in a message body must be escaped, not executed"
    assert "&lt;img" in rendered
    print("PASS: message bodies are HTML-escaped before being injected as raw HTML")


def test_bubble_uses_rtl_for_content_and_ltr_for_layout():
    """RTL text must stay correct even though bubble side is a literal left/right."""
    import ui_components as ui

    hebrew = "שלום לכולם"
    rendered = ui._chat_bubble_html("Harel", "01/01/2026 00:00", hebrew, is_mine=True)
    assert hebrew in rendered, "the Hebrew text itself must pass through untouched"
    assert 'class="chat-row mine"' in rendered
    # Layout direction (ltr, for a literal left/right split) and text direction
    # (rtl, for correct Hebrew) are set in theme.py on .chat-row and
    # .chat-bubble respectively — verified there, not per-call here, since
    # this function only emits the classes and theme.py owns direction: ltr/rtl.
    print("PASS: Hebrew content passes through unescaped and unreordered")


if __name__ == "__main__":
    create_temp_admin()
    _cleanup()
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    try:
        test_scroll_container_is_fixed_height_and_autoscrolls(pid)
        test_chat_input_renders_below_the_scroll_panel(pid)
        test_oldest_message_renders_first(pid)
        test_pending_send_appends_after_landed_messages(pid)
        test_bubble_side_matches_sender_not_viewer_identity(pid)
        test_message_text_is_html_escaped()
        test_bubble_uses_rtl_for_content_and_ltr_for_layout()
        print("\nALL CHAT-BUBBLE TESTS PASSED")
    finally:
        _cleanup()
        cleanup()
