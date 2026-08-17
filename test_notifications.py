"""Verify the notification system end to end.

Run with:  python test_notifications.py

Covers:
  1. send_notification with no contact details -> 'no-contact', never raises.
  2. send_notification with contact but unconfigured channel -> 'logged' (dry run).
  3. Real SMTP delivery against a local throwaway SMTP server, including the
     Hebrew body, subject, sender and recipient.
  4. Trigger 1: creating an urgent task notifies the assignee (exact message).
  5. Trigger 2: completing a task notifies its creator (exact message).
  6. Non-triggers: a regular task sends nothing; completing your own task
     sends nothing; un-checking a completed task sends nothing.
  7. The UI queues a Hebrew toast for the user.
"""

import asyncio
import email
import os
import threading
import time

from aiosmtpd.controller import Controller

import database as db
import notifications
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_notify_project"
OTHER_USER = "temp_test_notify_other"
ADMIN_EMAIL = "admin@example.test"
OTHER_EMAIL = "other@example.test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class Collector:
    """Minimal SMTP sink that records delivered messages."""

    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 (aiosmtpd API)
        self.messages.append(
            {
                "from": envelope.mail_from,
                "to": list(envelope.rcpt_tos),
                "raw": envelope.content.decode("utf8", errors="replace"),
            }
        )
        return "250 OK"


def _project_id():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    return row["id"] if row else None


def _seed():
    _unseed()
    create_temp_admin()
    db.add_user(OTHER_USER, "x" * 64, "user")
    db.set_user_contact(TEMP_ADMIN, ADMIN_EMAIL, "+972500000001")
    db.set_user_contact(OTHER_USER, OTHER_EMAIL, "+972500000002")
    return db.add_project(TEMP_PROJECT, TEMP_ADMIN)


def _unseed():
    pid = _project_id()
    if pid:
        db.delete_project(pid)
    db.delete_user(OTHER_USER)
    cleanup()


def _clear_smtp_env():
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
                "SMTP_USE_TLS", "NOTIFY_CHANNEL"):
        os.environ.pop(key, None)


def _ss(at, key, default=None):
    return at.session_state[key] if key in at.session_state else default


def _wait_for_sync(at, seconds=8):
    deadline = time.time() + seconds
    while time.time() < deadline and _ss(at, "_pending_writes"):
        time.sleep(0.3)
    time.sleep(0.5)
    return at.run()


class Spy:
    """Records send_notification calls instead of sending (thread-safe)."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, user_id, message):
        with self._lock:
            self.calls.append((user_id, message))
        return notifications.NotificationResult(True, "sent", "spy")

    def wait(self, count=1, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self.calls) >= count:
                    return True
            time.sleep(0.1)
        return False


# ---------------------------------------------------------------------------
# 1-3: the sender itself
# ---------------------------------------------------------------------------


def test_no_contact_details():
    _clear_smtp_env()
    db.set_user_contact(OTHER_USER, None, None)
    result = notifications.send_notification(OTHER_USER, "בדיקה")
    assert result.status == "no-contact", result
    assert result.ok is False
    db.set_user_contact(OTHER_USER, OTHER_EMAIL, "+972500000002")
    print("PASS: missing contact details -> 'no-contact', no exception")


def test_dry_run_when_unconfigured():
    _clear_smtp_env()
    assert notifications.is_configured() is False
    result = notifications.send_notification(TEMP_ADMIN, "בדיקת יומן")
    assert result.ok and result.status == "logged", result
    print("PASS: unconfigured channel -> dry run, message logged only")


def test_real_smtp_delivery():
    collector = Collector()
    controller = Controller(collector, hostname="127.0.0.1", port=8025)
    controller.start()
    try:
        _clear_smtp_env()
        os.environ.update({
            "SMTP_HOST": "127.0.0.1", "SMTP_PORT": "8025",
            "SMTP_FROM": "dashboard@example.test", "SMTP_USE_TLS": "false",
        })
        assert notifications.is_configured() is True
        body = notifications.URGENT_ASSIGNMENT.format(assignee=TEMP_ADMIN, title="משימה דחופה")
        result = notifications.send_notification(TEMP_ADMIN, body)
        assert result.ok and result.status == "sent", result

        assert len(collector.messages) == 1, collector.messages
        sent = collector.messages[0]
        assert sent["to"] == [ADMIN_EMAIL], sent["to"]
        assert sent["from"] == "dashboard@example.test", sent["from"]
        parsed = email.message_from_string(sent["raw"])
        subject = str(email.header.make_header(email.header.decode_header(parsed["Subject"])))
        assert subject == notifications.SUBJECT, subject
        payload = parsed.get_payload(decode=True).decode("utf-8")
        assert body in payload, payload
        print("PASS: real SMTP delivery — correct recipient, sender, Hebrew subject and body")
    finally:
        controller.stop()
        _clear_smtp_env()


# ---------------------------------------------------------------------------
# 4-7: triggers wired into the UI
# ---------------------------------------------------------------------------


def _open_project(pid):
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid)
    at = at.run()
    assert not at.exception, f"Dashboard crashed: {at.exception[0]}"
    return at


def test_urgent_assignment_trigger(pid, monkeypatched_spy):
    at = _open_project(pid)
    scope = f"project_{pid}"
    title = f"משימה דחופה {int(time.time())}"
    at.text_input(key=f"task_title_{scope}").set_value(title)
    at.checkbox(key=f"task_urgent_{scope}").set_value(True)
    at.selectbox(key=f"task_assignee_{scope}").select(OTHER_USER)
    submit = next(b for b in at.button if b.key and f"add_task_form_{scope}" in b.key)
    at = submit.set_value(True).run()
    assert not at.exception, f"Submit crashed: {at.exception[0]}"

    assert monkeypatched_spy.wait(1), "No notification was sent for the urgent task"
    recipient, message = monkeypatched_spy.calls[-1]
    assert recipient == OTHER_USER, f"Wrong recipient: {recipient}"
    expected = f"היי {OTHER_USER}, נוספה לך משימה דחופה: {title}."
    assert message == expected, f"\n got: {message!r}\nwant: {expected!r}"
    print("PASS: trigger 1 — urgent task notifies the assignee with the exact Hebrew message")

    at = _wait_for_sync(at)
    return at, title


def test_regular_task_sends_nothing(pid, spy):
    before = len(spy.calls)
    at = _open_project(pid)
    scope = f"project_{pid}"
    at.text_input(key=f"task_title_{scope}").set_value("משימה רגילה ללא התראה")
    submit = next(b for b in at.button if b.key and f"add_task_form_{scope}" in b.key)
    at = submit.set_value(True).run()
    at = _wait_for_sync(at)
    assert len(spy.calls) == before, f"Regular task should not notify: {spy.calls[before:]}"
    print("PASS: non-urgent task creation sends no notification")


def test_completion_trigger(pid, spy):
    """A task created by OTHER_USER, completed by TEMP_ADMIN -> notifies OTHER_USER."""
    db.add_task("משימה של השותף", TEMP_ADMIN, OTHER_USER, pid, "project")
    db.clear_task_caches()
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "משימה של השותף")

    at = _open_project(pid)
    before = len(spy.calls)
    at.checkbox(key=f"task_done_{task['id']}").set_value(True)
    at = at.run()
    assert not at.exception, f"Toggle crashed: {at.exception[0]}"

    assert spy.wait(before + 1), "No notification was sent on completion"
    recipient, message = spy.calls[-1]
    assert recipient == OTHER_USER, f"Should notify the creator, got {recipient}"
    expected = f"היי, המשימה 'משימה של השותף' בוצעה בהצלחה על ידי {TEMP_ADMIN}."
    assert message == expected, f"\n got: {message!r}\nwant: {expected!r}"
    # main.py consumes st.session_state["pending_toast"] during the rerun that
    # follows the callback, so assert on the rendered toast itself.
    toasts = [t.value for t in at.toast]
    assert any("התראה" in (t or "") for t in toasts), f"Expected a Hebrew toast, got {toasts}"
    print("PASS: trigger 2 — completion notifies the creator with the exact Hebrew message")
    print("PASS: UI queues a Hebrew toast for the notification")

    # Un-completing must not notify anyone. A completed task shows the green
    # "✅ הושלם" button instead of a checkbox, so click that to reopen it.
    at = _wait_for_sync(at)
    before = len(spy.calls)
    undone = next(b for b in at.button if b.key == f"task_undone_{task['id']}")
    at = undone.set_value(True).run()
    at = _wait_for_sync(at)
    assert len(spy.calls) == before, f"Un-completing should not notify: {spy.calls[before:]}"
    print("PASS: un-checking a completed task sends no notification")


def test_self_completion_sends_nothing(pid, spy):
    db.add_task("משימה שלי", TEMP_ADMIN, TEMP_ADMIN, pid, "project")
    db.clear_task_caches()
    task = next(t for t in db.get_tasks(project_id=pid) if t["title"] == "משימה שלי")
    at = _open_project(pid)
    before = len(spy.calls)
    at.checkbox(key=f"task_done_{task['id']}").set_value(True)
    at = at.run()
    at = _wait_for_sync(at)
    assert len(spy.calls) == before, f"Self-completion should not notify: {spy.calls[before:]}"
    print("PASS: completing your own task sends no notification (NOTIFY_SELF=False)")


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    pid = _seed()
    real_send = notifications.send_notification
    try:
        test_no_contact_details()
        test_dry_run_when_unconfigured()
        test_real_smtp_delivery()

        spy = Spy()
        notifications.send_notification = spy  # intercept the leaf sender
        test_urgent_assignment_trigger(pid, spy)
        test_regular_task_sends_nothing(pid, spy)
        test_completion_trigger(pid, spy)
        test_self_completion_sends_nothing(pid, spy)
    finally:
        notifications.send_notification = real_send
        _clear_smtp_env()
        _unseed()
    print("\nALL NOTIFICATION TESTS PASSED")
