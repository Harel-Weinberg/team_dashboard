"""Verify the on-demand mailto: notification links.

Run with:  python test_mailto_links.py

Covers:
  1. Open task -> addressed to the assignee, correct Hebrew subject/body.
  2. Urgent open task -> "[דחוף]" prefix in the subject.
  3. Completed task -> addressed to the creator, completion subject/body.
  4. Completed task, creator without an email -> falls back to TEAM_EMAIL.
  5. No recipient email at all -> None (the UI hides the icon).
  6. Titles containing &, ?, # and newlines stay intact through encoding.
  7. The task row renders a valid <a href="mailto:..."> icon (AppTest), and
     hides it when the recipient has no email.
"""

import os
import time
from urllib.parse import parse_qs, unquote, urlsplit

import database as db
import notifications
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_mailto_project"
OTHER_USER = "temp_test_mailto_other"
ADMIN_EMAIL = "admin@example.test"
OTHER_EMAIL = "other@example.test"
TEAM_EMAIL = "team@example.test"


def _project_id():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    return row["id"] if row else None


def _seed():
    _unseed()
    create_temp_admin()
    db.add_user(OTHER_USER, "x" * 64, "user")
    db.set_user_contact(TEMP_ADMIN, ADMIN_EMAIL, None)
    db.set_user_contact(OTHER_USER, OTHER_EMAIL, None)
    return db.add_project(TEMP_PROJECT, TEMP_ADMIN)


def _unseed():
    pid = _project_id()
    if pid:
        db.delete_project(pid)
    db.delete_user(OTHER_USER)
    cleanup()
    os.environ.pop("TEAM_EMAIL", None)


def _parse(link: str) -> dict:
    """Split a mailto: link into {to, subject, body}, fully decoded."""
    parts = urlsplit(link)
    assert parts.scheme == "mailto", f"Not a mailto link: {link}"
    query = parse_qs(parts.query, keep_blank_values=True)
    return {
        "to": unquote(parts.path),
        "subject": query.get("subject", [""])[0],
        "body": query.get("body", [""])[0],
    }


def _task(**overrides) -> dict:
    task = {
        "title": "לתקן את הבאג בטופס",
        "assignee": OTHER_USER,
        "created_by": TEMP_ADMIN,
        "is_done": False,
        "is_urgent": False,
    }
    task.update(overrides)
    return task


def test_open_task_link():
    db.get_contacts.clear()
    link = notifications.build_mailto_link(_task())
    parsed = _parse(link)
    assert parsed["to"] == OTHER_EMAIL, parsed["to"]
    assert parsed["subject"] == "התראה על משימה: לתקן את הבאג בטופס", parsed["subject"]
    expected_body = (
        f"היי {OTHER_USER},\n\nזוהי התראה לגבי המשימה הבאה:\n"
        "לתקן את הבאג בטופס\n\nלטיפולך בהקדם."
    )
    assert parsed["body"] == expected_body, f"\n got: {parsed['body']!r}\nwant: {expected_body!r}"
    assert "%D7" in link, "Hebrew should be percent-encoded in the raw link"
    assert " " not in link and "\n" not in link, f"Raw link must be fully encoded: {link}"
    print("PASS: open task -> assignee, correct Hebrew subject and body (encoded)")


def test_urgent_prefix():
    link = notifications.build_mailto_link(_task(is_urgent=True))
    subject = _parse(link)["subject"]
    assert subject == "[דחוף] התראה על משימה: לתקן את הבאג בטופס", subject
    print("PASS: urgent open task -> subject carries the [דחוף] prefix")


def test_completed_task_link():
    link = notifications.build_mailto_link(_task(is_done=True))
    parsed = _parse(link)
    assert parsed["to"] == ADMIN_EMAIL, f"Should go to the creator, got {parsed['to']}"
    assert parsed["subject"] == "משימה הושלמה: לתקן את הבאג בטופס", parsed["subject"]
    expected_body = (
        "היי,\n\nהמשימה 'לתקן את הבאג בטופס' סומנה כבוצעה בהצלחה.\n\n"
        "בברכה,\nצוות AI וחדשנות"
    )
    assert parsed["body"] == expected_body, f"\n got: {parsed['body']!r}\nwant: {expected_body!r}"
    print("PASS: completed task -> creator, completion subject and signed body")


def test_team_email_fallback():
    db.set_user_contact(TEMP_ADMIN, None, None)
    db.get_contacts.clear()
    assert notifications.build_mailto_link(_task(is_done=True)) is None, (
        "Without TEAM_EMAIL there is no recipient"
    )
    os.environ["TEAM_EMAIL"] = TEAM_EMAIL
    link = notifications.build_mailto_link(_task(is_done=True))
    assert _parse(link)["to"] == TEAM_EMAIL, link
    os.environ.pop("TEAM_EMAIL")
    db.set_user_contact(TEMP_ADMIN, ADMIN_EMAIL, None)
    db.get_contacts.clear()
    print("PASS: completed task falls back to TEAM_EMAIL when the creator has none")


def test_missing_email_returns_none():
    db.set_user_contact(OTHER_USER, None, None)
    db.get_contacts.clear()
    assert notifications.build_mailto_link(_task()) is None, "No assignee email -> no link"
    assert notifications.build_mailto_link(_task(assignee=None)) is None, "No assignee -> no link"
    assert notifications.build_mailto_link(_task(assignee="ghost_user")) is None, (
        "Unknown assignee -> no link"
    )
    db.set_user_contact(OTHER_USER, OTHER_EMAIL, None)
    db.get_contacts.clear()
    print("PASS: missing/unknown email -> None (icon hidden), no crash")


def test_special_characters_survive_encoding():
    tricky = "A&B ?x #y = 100% (בדיקה)"
    link = notifications.build_mailto_link(_task(title=tricky))
    parsed = _parse(link)
    assert parsed["subject"] == f"התראה על משימה: {tricky}", parsed["subject"]
    assert tricky in parsed["body"], parsed["body"]
    # The raw link must contain exactly one '&' (the query separator) and one '?'.
    assert link.count("&") == 1 and link.count("?") == 1, link
    assert "#" not in link, f"'#' must be encoded, else it becomes a fragment: {link}"
    print("PASS: titles with & ? # % and parentheses encode safely")


def test_ui_renders_icon(pid):
    db.add_task("משימה עם מייל", OTHER_USER, TEMP_ADMIN, pid, "project")
    db.get_tasks.clear()
    db.get_contacts.clear()

    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, f"Dashboard crashed: {at.exception[0]}"

    blocks = [m.value or "" for m in at.markdown if "משימה עם מייל" in (m.value or "")]
    assert blocks, "Task row not rendered"
    row = blocks[0]
    assert 'class="task-mail"' in row, f"Mail icon missing: {row}"
    assert 'href="mailto:' in row and "&amp;body=" in row, (
        f"href must be an escaped mailto link: {row}"
    )
    assert "📧" in row, "Expected the 📧 icon"
    print("PASS: task row renders the 📧 mailto icon with a properly escaped href")

    # Now remove the assignee's email — the icon must disappear.
    db.set_user_contact(OTHER_USER, None, None)
    db.get_contacts.clear()
    at = at.run()
    row = next(m.value for m in at.markdown if "משימה עם מייל" in (m.value or ""))
    assert "task-mail" not in row, f"Icon should be hidden without an email: {row}"
    print("PASS: icon is hidden when the recipient has no email on file")
    db.set_user_contact(OTHER_USER, OTHER_EMAIL, None)
    db.get_contacts.clear()


if __name__ == "__main__":
    pid = _seed()
    try:
        test_open_task_link()
        test_urgent_prefix()
        test_completed_task_link()
        test_team_email_fallback()
        test_missing_email_returns_none()
        test_special_characters_survive_encoding()
        test_ui_renders_icon(pid)
    finally:
        _unseed()
    print("\nALL MAILTO TESTS PASSED")
