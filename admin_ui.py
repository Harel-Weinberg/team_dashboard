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
import optimistic
from ui_components import fmt_ts

MIN_PASSWORD_LEN = 6
MIN_USERNAME_LEN = 2
MAX_USERNAME_LEN = 32
# Unicode word characters (Latin + Hebrew letters, digits, underscore) plus . -
# No spaces: the username is typed by hand on the login screen.
_USERNAME_RE = re.compile(rf"^[\w.\-]{{{MIN_USERNAME_LEN},{MAX_USERNAME_LEN}}}$", re.UNICODE)


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
        return "Please enter a username."
    if not _USERNAME_RE.fullmatch(name):
        return (
            f"Username must be {MIN_USERNAME_LEN}-{MAX_USERNAME_LEN} characters, "
            "using letters, digits, dot, hyphen or underscore (no spaces)."
        )
    if current_name is not None and name == current_name:
        return "That is already the current username."
    if db.username_exists(name, exclude=current_name):
        return f"A user named '{name}' already exists."
    return None


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
    add_tab, rename_tab, password_tab, delete_tab = st.tabs(
        ["➕ Add user", "✏️ Change username", "🔑 Change password", "🗑️ Delete user"]
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
                    error = _validate_username(name) or _validate_password(
                        new_password, new_confirm
                    )
                if error:
                    st.error(error)
                elif not db.add_user(name, auth.hash_password(new_password), new_role):
                    st.error(f"A user named '{name}' already exists.")
                else:
                    _flash("success", f"User '{name}' ({new_role}) created.")
                    st.rerun()

    # --- Change username ------------------------------------------------------
    with rename_tab:
        st.caption(
            "Renaming a user rewrites the author name on all of their past "
            "activity (projects, specs, tasks, notes and chat messages), so "
            "nothing loses its attribution."
        )
        with st.form("rename_user_form", clear_on_submit=False):
            target = st.selectbox("User to rename", usernames, key="rename_target")
            new_name = st.text_input("New username", key="rename_new_name")
            if st.form_submit_button("Update username", type="primary"):
                name = new_name.strip()
                error = _validate_username(name, current_name=target)
                if error:
                    st.error(error)
                else:
                    # Let in-flight optimistic writes land first — a late write
                    # would still be tagged with the old username.
                    if not optimistic.wait_for_pending():
                        st.warning(
                            "Some changes are still syncing. Please try again in a moment."
                        )
                    else:
                        reattributed = db.rename_user(target, name)
                        if reattributed is None:
                            st.error(
                                f"Could not rename '{target}' — the name may have just "
                                "been taken, or the user no longer exists."
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
                                f"Username changed: '{target}' → '{name}'. "
                                f"{reattributed} historical record(s) re-attributed."
                                + ("" if target == current_user
                                   else " Ask them to sign in with the new username."),
                            )
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
