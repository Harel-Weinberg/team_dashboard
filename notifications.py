"""
notifications.py — Outbound notifications (email now, WhatsApp-ready).

Design:
  * send_notification(user_id, message) is the single entry point. It resolves
    the recipient's contact details from the `users` table and sends via the
    configured channel. Every attempt is logged to the console, so the whole
    flow is testable locally with no SMTP account at all.
  * dispatch() queues the send on the shared background thread pool
    (see optimistic.py) so the Streamlit UI never blocks on the network, and
    returns a ready-made Hebrew toast line for the caller to show.
  * Configuration comes from environment variables. bootstrap_from_secrets()
    copies [smtp] out of st.secrets into os.environ once, on the main thread,
    so worker threads only ever read os.environ (thread-safe).

Environment variables:
    NOTIFY_CHANNEL   "email" (default) or "whatsapp"
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_TLS
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM   (WhatsApp)

If the channel isn't configured, nothing is sent and the message is logged
("dry run") — the app keeps working and local testing stays easy.
"""

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import streamlit as st

import database as db
import optimistic

LOG = logging.getLogger("team_dashboard.notifications")
if not LOG.handlers:  # console logging for local testing
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [NOTIFY] %(levelname)s: %(message)s"))
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)

SUBJECT = "עדכון ממערכת המשימות — צוות AI וחדשנות"

# Message templates (Hebrew).
URGENT_ASSIGNMENT = "היי {assignee}, נוספה לך משימה דחופה: {title}."
TASK_COMPLETED = "היי, המשימה '{title}' בוצעה בהצלחה על ידי {completed_by}."

# Notifying you about your own action is just noise. Flip to True to also
# notify a task's creator when they complete their own task.
NOTIFY_SELF = False


@dataclass
class NotificationResult:
    ok: bool
    status: str  # 'sent' | 'logged' | 'no-contact'
    detail: str = ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def bootstrap_from_secrets() -> None:
    """Copy [smtp] / [twilio] from st.secrets into os.environ (main thread only).

    Lets Streamlit Cloud deployments configure notifications through the app's
    Secrets UI while worker threads keep reading plain environment variables.
    """
    for section, prefix in (("smtp", "SMTP_"), ("twilio", "TWILIO_")):
        try:
            values = st.secrets[section]
        except (KeyError, FileNotFoundError):
            continue
        for key, value in values.items():
            env_key = key.upper() if key.upper().startswith(prefix) else f"{prefix}{key.upper()}"
            os.environ.setdefault(env_key, str(value))
    if "channel" not in os.environ:
        try:
            os.environ.setdefault("NOTIFY_CHANNEL", str(st.secrets["notifications"]["channel"]))
        except (KeyError, FileNotFoundError):
            pass


def channel() -> str:
    return os.environ.get("NOTIFY_CHANNEL", "email").strip().lower()


def is_configured() -> bool:
    """True when the active channel has enough configuration to actually send."""
    if channel() == "whatsapp":
        return all(
            os.environ.get(k)
            for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM")
        )
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


def _send_email(to_address: str, message: str) -> str:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ["SMTP_FROM"]
    use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() != "false"

    email = EmailMessage()
    email["Subject"] = SUBJECT
    email["From"] = sender
    email["To"] = to_address
    email.set_content(message)  # EmailMessage handles UTF-8 (Hebrew) itself

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(email)
    return f"email→{to_address}"


def _send_whatsapp(phone: str, message: str) -> str:
    """Skeleton for WhatsApp via Twilio.

    Kept dependency-free on purpose: install `twilio`, then enable the block
    below and set NOTIFY_CHANNEL=whatsapp plus the TWILIO_* variables.
    """
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    sender = os.environ["TWILIO_WHATSAPP_FROM"]  # e.g. "whatsapp:+14155238886"
    to = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

    try:
        from twilio.rest import Client  # noqa: PLC0415 — optional dependency
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(
            "WhatsApp channel selected but the 'twilio' package is not installed "
            "(pip install twilio)."
        ) from exc

    Client(account_sid, auth_token).messages.create(from_=sender, to=to, body=message)
    return f"whatsapp→{to}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_notification(user_id: str, message: str) -> NotificationResult:
    """Send `message` to the user named `user_id`. Always logs; never blocks the UI.

    Runs on a worker thread (see dispatch) — it must not touch st.session_state.
    """
    contact = db.get_contacts().get(user_id, {})
    target = contact.get("phone") if channel() == "whatsapp" else contact.get("email")

    LOG.info("to=%s channel=%s target=%s message=%s", user_id, channel(), target or "-", message)

    if not target:
        LOG.warning("no %s on file for '%s' — logged only", channel(), user_id)
        return NotificationResult(False, "no-contact", f"no contact details for {user_id}")

    if not is_configured():
        LOG.warning("%s channel is not configured — dry run (message logged only)", channel())
        return NotificationResult(True, "logged", "channel not configured; logged only")

    detail = _send_whatsapp(target, message) if channel() == "whatsapp" else _send_email(
        target, message
    )
    LOG.info("delivered %s", detail)
    return NotificationResult(True, "sent", detail)


def dispatch(recipient: str, message: str) -> str:
    """Queue a notification in the background. Returns a Hebrew toast line.

    Failures on the worker thread are surfaced by optimistic.report_sync_failures().
    """
    optimistic.submit_write(f"התראה ל-{recipient}", send_notification, recipient, message)

    contact = db.get_contacts().get(recipient, {})
    has_target = bool(contact.get("phone") if channel() == "whatsapp" else contact.get("email"))
    if not has_target:
        return f"📣 אין פרטי קשר ל-{recipient} — ההתראה נרשמה ביומן"
    if not is_configured():
        return f"📣 ההתראה ל-{recipient} נרשמה ביומן (ערוץ השליחה לא מוגדר)"
    return f"📣 התראה נשלחה ל-{recipient}!"


def notify_urgent_assignment(assignee: str, task_title: str) -> str:
    """Trigger 1 — a new urgent task was assigned."""
    return dispatch(assignee, URGENT_ASSIGNMENT.format(assignee=assignee, title=task_title))


def notify_task_completed(creator: str | None, task_title: str, completed_by: str) -> str | None:
    """Trigger 2 — a task moved from open to completed. Returns None if nobody to notify."""
    if not creator:
        return None
    if creator == completed_by and not NOTIFY_SELF:
        return None
    return dispatch(
        creator, TASK_COMPLETED.format(title=task_title, completed_by=completed_by)
    )
