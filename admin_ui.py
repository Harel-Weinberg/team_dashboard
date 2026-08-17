"""
admin_ui.py — User Management page (admins only).

Lets an admin view all users, add a user, change any user's password, and
delete a user. Guard rails: you cannot delete yourself, and you cannot delete
the last remaining admin (so the team can never be locked out).
"""

import re

import streamlit as st

import auth
import database as db
import notifications
import optimistic
from ui_components import fmt_ts

MIN_PASSWORD_LEN = 6
MIN_USERNAME_LEN = 2
MAX_USERNAME_LEN = 32
# Unicode word characters (Latin + Hebrew letters, digits, underscore) plus . -
# No spaces: the username is typed by hand on the login screen.
_USERNAME_RE = re.compile(rf"^[\w.\-]{{{MIN_USERNAME_LEN},{MAX_USERNAME_LEN}}}$", re.UNICODE)
# Deliberately permissive: enough to catch typos, not a full RFC 5322 parser.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[\d\-\s()]{7,20}$")


def _flash(kind: str, message: str) -> None:
    """Queue a message that survives the st.rerun() after a successful action."""
    st.session_state["admin_flash"] = (kind, message)


def _show_flash() -> None:
    kind, message = st.session_state.pop("admin_flash", (None, None))
    if kind:
        getattr(st, kind)(message)


def _validate_username(name: str, current_name: str | None = None) -> str | None:
    """Return an error message, or None if the username is acceptable.

    `current_name` is the name being replaced (excluded from the duplicate
    check, so a user can change only the letter-casing of their own name).
    """
    if not name:
        return "נא להזין שם משתמש."
    if not _USERNAME_RE.fullmatch(name):
        return (
            f"שם המשתמש חייב להכיל {MIN_USERNAME_LEN}-{MAX_USERNAME_LEN} תווים: "
            "אותיות, ספרות, נקודה, מקף או קו תחתון (ללא רווחים)."
        )
    if current_name is not None and name == current_name:
        return "זה כבר שם המשתמש הנוכחי."
    if db.username_exists(name, exclude=current_name):
        return f"משתמש בשם '{name}' כבר קיים."
    return None


def _validate_password(password: str, confirm: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"הסיסמה חייבת להכיל לפחות {MIN_PASSWORD_LEN} תווים."
    if password != confirm:
        return "הסיסמאות אינן תואמות."
    return None


def render_user_management() -> None:
    if not auth.is_admin():
        st.error("🔒 הדף הזה זמין למנהלים בלבד.")
        return

    current_user = st.session_state["user"]

    st.title("👥 ניהול משתמשים")
    _show_flash()

    # --- Current users -------------------------------------------------------
    users = db.get_users_detailed()
    st.subheader(f"משתמשים קיימים ({len(users)})")
    st.dataframe(
        [
            {
                "משתמש": u["username"],
                "תפקיד": "🛡️ מנהל" if u["role"] == "admin" else "👤 משתמש",
                "מייל": u.get("email") or "—",
                "טלפון": u.get("phone") or "—",
                "נוצר": fmt_ts(u["created_at"]),
            }
            for u in users
        ],
        use_container_width=True,
        hide_index=True,
    )

    usernames = [u["username"] for u in users]
    add_tab, rename_tab, password_tab, contact_tab, delete_tab = st.tabs(
        [
            "➕ משתמש חדש", "✏️ שינוי שם משתמש", "🔑 שינוי סיסמה",
            "📧 פרטי קשר", "🗑️ מחיקת משתמש",
        ]
    )

    # --- Add user -------------------------------------------------------------
    with add_tab:
        with st.form("add_user_form", clear_on_submit=True):
            new_username = st.text_input("שם משתמש")
            new_role = st.selectbox("תפקיד", ["user", "admin"], format_func=lambda r: "מנהל" if r == "admin" else "משתמש")
            new_password = st.text_input("סיסמה", type="password")
            new_confirm = st.text_input("אימות סיסמה", type="password")
            if st.form_submit_button("יצירת משתמש", type="primary"):
                name = new_username.strip()
                error = None
                if not name:
                    error = "נא להזין שם משתמש."
                else:
                    error = _validate_username(name) or _validate_password(
                        new_password, new_confirm
                    )
                if error:
                    st.error(error)
                elif not db.add_user(name, auth.hash_password(new_password), new_role):
                    st.error(f"משתמש בשם '{name}' כבר קיים.")
                else:
                    _flash("success", f"המשתמש '{name}' נוצר בהצלחה ({new_role}).")
                    st.rerun()

    # --- Change username ------------------------------------------------------
    with rename_tab:
        st.caption(
            "שינוי שם משתמש מעדכן את שם היוצר בכל הפעילות הקודמת שלו "
            "(פרויקטים, אפיונים, משימות, הערות והודעות), כך שאף פעולה "
            "לא מאבדת את השיוך שלה."
        )
        with st.form("rename_user_form", clear_on_submit=False):
            target = st.selectbox("המשתמש לשינוי", usernames, key="rename_target")
            new_name = st.text_input("שם משתמש חדש", key="rename_new_name")
            if st.form_submit_button("עדכון שם המשתמש", type="primary"):
                name = new_name.strip()
                error = _validate_username(name, current_name=target)
                if error:
                    st.error(error)
                else:
                    # Let in-flight optimistic writes land first — a late write
                    # would still be tagged with the old username.
                    if not optimistic.wait_for_pending():
                        st.warning(
                            "חלק מהשינויים עדיין מסתנכרנים. נסו שוב בעוד רגע."
                        )
                    else:
                        reattributed = db.rename_user(target, name)
                        if reattributed is None:
                            st.error(
                                f"לא ניתן לשנות את השם של '{target}' — ייתכן שהשם נתפס "
                                "כרגע או שהמשתמש אינו קיים יותר."
                            )
                        else:
                            if target == current_user:
                                # Keep the session (and all future identity
                                # tagging) in sync with the new name.
                                st.session_state["user"] = name
                                optimistic.discard_echoes()
                            st.session_state.pop("rename_new_name", None)
                            _flash(
                                "success",
                                f"שם המשתמש שונה: '{target}' → '{name}'. "
                                f"עודכנו {reattributed} רשומות היסטוריות."
                                + ("" if target == current_user
                                   else " בקשו ממנו/ה להתחבר עם השם החדש."),
                            )
                            st.rerun()

    # --- Change password --------------------------------------------------------
    with password_tab:
        with st.form("change_password_form", clear_on_submit=True):
            target = st.selectbox("משתמש", usernames, key="pw_target")
            password = st.text_input("סיסמה חדשה", type="password")
            confirm = st.text_input("אימות הסיסמה החדשה", type="password")
            if st.form_submit_button("עדכון הסיסמה", type="primary"):
                error = _validate_password(password, confirm)
                if error:
                    st.error(error)
                else:
                    db.set_user_password(target, auth.hash_password(password))
                    _flash("success", f"הסיסמה של '{target}' עודכנה.")
                    st.rerun()

    # --- Contact details (used by the notification system) -----------------------
    with contact_tab:
        st.caption(
            "כתובת המייל משמשת לשליחת התראות: משימה דחופה שהוקצתה למשתמש, "
            "וסיום משימה שהוא פתח. מספר הטלפון נשמר לשימוש עתידי בוואטסאפ."
        )
        if not notifications.is_configured():
            st.info(
                f"ערוץ השליחה ({notifications.channel()}) אינו מוגדר — ההתראות "
                "נרשמות ליומן המערכת בלבד. הגדירו SMTP_* בקובץ הסודות כדי לשלוח בפועל."
            )
        with st.form("contact_form", clear_on_submit=False):
            target = st.selectbox("משתמש", usernames, key="contact_target")
            existing = next((u for u in users if u["username"] == target), {})
            email = st.text_input(
                "כתובת מייל", value=existing.get("email") or "", key="contact_email",
                placeholder="name@example.com",
            )
            phone = st.text_input(
                "טלפון (לוואטסאפ)", value=existing.get("phone") or "", key="contact_phone",
                placeholder="+972501234567",
            )
            if st.form_submit_button("שמירת פרטי הקשר", type="primary"):
                clean_email = email.strip()
                clean_phone = phone.strip()
                if clean_email and not _EMAIL_RE.fullmatch(clean_email):
                    st.error("כתובת המייל אינה תקינה.")
                elif clean_phone and not _PHONE_RE.fullmatch(clean_phone):
                    st.error("מספר הטלפון אינו תקין (לדוגמה: +972501234567).")
                else:
                    db.set_user_contact(target, clean_email, clean_phone)
                    _flash("success", f"פרטי הקשר של '{target}' עודכנו.")
                    st.rerun()

    # --- Delete user --------------------------------------------------------------
    with delete_tab:
        deletable = [name for name in usernames if name != current_user]
        if not deletable:
            st.info("אין משתמשים אחרים למחיקה (לא ניתן למחוק את עצמך).")
        else:
            target = st.selectbox("המשתמש למחיקה", deletable, key="delete_target")
            confirmed = st.checkbox(f"כן, למחוק את '{target}' לצמיתות", key="delete_confirm")
            if st.button("🗑️ מחיקת המשתמש", type="primary", disabled=not confirmed):
                target_row = db.get_user(target)
                if target_row and target_row["role"] == "admin" and db.count_admins() <= 1:
                    st.error("לא ניתן למחוק את המנהל האחרון שנותר.")
                else:
                    db.delete_user(target)
                    _flash("success", f"המשתמש '{target}' נמחק.")
                    st.rerun()
