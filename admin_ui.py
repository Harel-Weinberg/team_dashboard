"""
admin_ui.py — User Management page (admins only).

Lets an admin view all users, add a user, change any user's password, and
delete a user. Guard rails: you cannot delete yourself, and you cannot delete
the last remaining admin (so the team can never be locked out).
"""

import streamlit as st

import auth
import database as db
from ui_components import fmt_ts

MIN_PASSWORD_LEN = 6


def _flash(kind: str, message: str) -> None:
    """Queue a message that survives the st.rerun() after a successful action."""
    st.session_state["admin_flash"] = (kind, message)


def _show_flash() -> None:
    kind, message = st.session_state.pop("admin_flash", (None, None))
    if kind:
        getattr(st, kind)(message)


def _validate_password(password: str, confirm: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if password != confirm:
        return "Passwords do not match."
    return None


def render_user_management() -> None:
    if not auth.is_admin():
        st.error("🔒 This page is only available to admins.")
        return

    current_user = st.session_state["user"]

    st.title("👥 User Management")
    _show_flash()

    # --- Current users -------------------------------------------------------
    users = db.get_users_detailed()
    st.subheader(f"Current users ({len(users)})")
    st.dataframe(
        [
            {
                "User": u["username"],
                "Role": "🛡️ admin" if u["role"] == "admin" else "👤 user",
                "Created": fmt_ts(u["created_at"]),
            }
            for u in users
        ],
        use_container_width=True,
        hide_index=True,
    )

    usernames = [u["username"] for u in users]
    add_tab, password_tab, delete_tab = st.tabs(
        ["➕ Add user", "🔑 Change password", "🗑️ Delete user"]
    )

    # --- Add user -------------------------------------------------------------
    with add_tab:
        with st.form("add_user_form", clear_on_submit=True):
            new_username = st.text_input("Username")
            new_role = st.selectbox("Role", ["user", "admin"])
            new_password = st.text_input("Password", type="password")
            new_confirm = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create user", type="primary"):
                name = new_username.strip()
                error = None
                if not name:
                    error = "Please enter a username."
                else:
                    error = _validate_password(new_password, new_confirm)
                if error:
                    st.error(error)
                elif not db.add_user(name, auth.hash_password(new_password), new_role):
                    st.error(f"A user named '{name}' already exists.")
                else:
                    _flash("success", f"User '{name}' ({new_role}) created.")
                    st.rerun()

    # --- Change password --------------------------------------------------------
    with password_tab:
        with st.form("change_password_form", clear_on_submit=True):
            target = st.selectbox("User", usernames, key="pw_target")
            password = st.text_input("New password", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update password", type="primary"):
                error = _validate_password(password, confirm)
                if error:
                    st.error(error)
                else:
                    db.set_user_password(target, auth.hash_password(password))
                    _flash("success", f"Password updated for '{target}'.")
                    st.rerun()

    # --- Delete user --------------------------------------------------------------
    with delete_tab:
        deletable = [name for name in usernames if name != current_user]
        if not deletable:
            st.info("There are no other users to delete (you cannot delete yourself).")
        else:
            target = st.selectbox("User to delete", deletable, key="delete_target")
            confirmed = st.checkbox(f"Yes, permanently delete '{target}'", key="delete_confirm")
            if st.button("🗑️ Delete user", type="primary", disabled=not confirmed):
                target_row = db.get_user(target)
                if target_row and target_row["role"] == "admin" and db.count_admins() <= 1:
                    st.error("Cannot delete the last remaining admin.")
                else:
                    db.delete_user(target)
                    _flash("success", f"User '{target}' deleted.")
                    st.rerun()
