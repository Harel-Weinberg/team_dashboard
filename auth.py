"""
auth.py — Database-driven authentication.

Users live in the `users` table in PostgreSQL (Supabase) and are managed from
the admin-only "User Management" page. Passwords are stored as SHA-256 hashes
— never in plaintext, and no longer in secrets.toml.

If the users table is empty, database.init_db() seeds two default admins
(Harel / Yitzhak) so the team can never be locked out.

After login, st.session_state holds:
  * "user" — the active username (used to identity-tag every action)
  * "role" — 'admin' or 'user' (gates the User Management page)
"""

import hmac

import psycopg2
import streamlit as st

import database as db


def hash_password(password: str) -> str:
    return db.sha256_hex(password)


def _verify(username: str, password: str) -> bool:
    user = db.get_user(username)
    if not user or not user.get("password_hash"):
        return False
    return hmac.compare_digest(user["password_hash"].lower(), hash_password(password))


def is_admin() -> bool:
    return st.session_state.get("role") == "admin"


def require_login() -> bool:
    """Render the login screen if needed. Returns True once a user is signed in."""
    if st.session_state.get("user"):
        return True

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.title("🚀 AI & Tech Innovation")
        st.caption("Project Management & Control Dashboard")

        try:
            usernames = db.get_users()
        except psycopg2.OperationalError as exc:
            st.error(f"Cannot reach the database — check .streamlit/secrets.toml.\n\n{exc}")
            return False

        with st.form("login_form"):
            username = st.selectbox("User", usernames)
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")
        if submitted:
            if _verify(username, password):
                user = db.get_user(username)
                st.session_state["user"] = username
                st.session_state["role"] = user["role"]
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
    return False


def logout() -> None:
    for key in list(st.session_state.keys()):
        if key in ("user", "role", "view", "task_done_override", "_pending_writes") or str(
            key
        ).startswith("optimistic_"):
            st.session_state.pop(key, None)
    st.rerun()
