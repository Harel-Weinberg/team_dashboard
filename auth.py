"""
auth.py — Database-driven authentication with a modern, minimalist login screen.

Users live in the `users` table in PostgreSQL (Supabase) and are managed from
the admin-only "User Management" page. Passwords are stored as SHA-256 hashes
— never in plaintext, and never in secrets.toml.

The login view injects scoped CSS (hidden Streamlit chrome, soft radial
gradient background, centered white card, underline inputs, dark rounded
submit button). The CSS is only emitted while logged out, so the normal app
chrome returns after sign-in.

After login, st.session_state holds:
  * "user" — the active username (used to identity-tag every action)
  * "role" — 'admin' or 'user' (gates the User Management page)
"""

import hmac

import psycopg2
import streamlit as st

import database as db

_LOGO_SVG = """
<svg viewBox="0 0 20 23" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M13.3788 1.97186C32.1235 12.016 3.26806 30.8273 0.434403 17.404C-0.483542 13.067 5.14386 11.2444 2.53636 7.21346C-0.124346 3.10266 7.72475 -1.06135 13.3788 1.97186Z" fill="url(#gFlowExpanded)" />
    <path d="M6.52802 11.9759C6.39499 11.9759 6.26195 11.9227 6.15552 11.8163C5.95597 11.6168 5.95597 11.2842 6.15552 11.0846L8.43043 8.823C8.62999 8.62345 8.96257 8.62345 9.16213 8.823L11.4104 11.058C11.61 11.2576 11.61 11.5901 11.4104 11.7897C11.2109 11.9893 10.8783 11.9893 10.6787 11.7897L8.81624 9.9272L6.90052 11.8296C6.79409 11.9227 6.66106 11.9759 6.52802 11.9759Z" fill="white" />
    <path d="M15.1747 9.64799L9.17481 3.688C8.97526 3.48844 8.64267 3.48844 8.44312 3.688L3.21482 8.88969C3.36116 9.99388 2.89553 10.9517 2.29688 11.9096V17.2576C2.29688 17.5503 2.52304 17.7765 2.81571 17.7765H8.77571C9.06838 17.7765 9.29454 17.5503 9.29454 17.2576V12.3752C9.29454 12.0825 9.06838 11.8564 8.77571 11.8564C8.48303 11.8564 8.25687 12.0825 8.25687 12.3752V16.7388H3.33455V10.22L8.81562 4.77889L14.2967 10.22V16.7388H11.5828C11.2901 16.7388 11.0639 16.9649 11.0639 17.2576C11.0639 17.5503 11.2901 17.7765 11.5828 17.7765H14.8155C15.1082 17.7765 15.3344 17.5503 15.3344 17.2576V10.0205C15.3211 9.87415 15.2678 9.74111 15.1747 9.64799Z" fill="white" />
    <defs>
        <linearGradient id="gFlowExpanded" x1="1.28065" y1="18.9562" x2="15.7982" y2="3.86951" gradientUnits="userSpaceOnUse">
            <stop stop-color="#A71E85" />
            <stop offset="0.1345" stop-color="#A0438E" />
            <stop offset="0.4254" stop-color="#8C72A3" />
            <stop offset="0.8472" stop-color="#66A4C1" />
            <stop offset="1" stop-color="#4FB5CC" />
        </linearGradient>
    </defs>
</svg>
"""

_LOGIN_CSS = """
<style>
/* --- Hide Streamlit chrome on the login view -------------------------- */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stDecoration"],
footer {
    display: none !important;
}

/* --- Soft radial gradient background ----------------------------------- */
.stApp {
    background:
        radial-gradient(circle at 15% 15%, rgba(79, 181, 204, 0.18) 0%, rgba(79, 181, 204, 0) 45%),
        radial-gradient(circle at 85% 80%, rgba(167, 30, 133, 0.14) 0%, rgba(167, 30, 133, 0) 50%),
        radial-gradient(circle at 50% 40%, #ffffff 0%, #f4f6fb 60%, #edeaf6 100%);
}

.block-container {
    padding-top: 10vh;
}

/* --- Centered login card (the form itself is the card) ------------------ */
[data-testid="stForm"] {
    background: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.7);
    border-radius: 20px;
    padding: 2.6rem 2.3rem 2.2rem;
    box-shadow: 0 20px 50px rgba(60, 60, 120, 0.14);
}

.login-logo {
    text-align: center;
    margin-bottom: 0.4rem;
}
.login-logo svg {
    width: 64px;
    height: 74px;
}
.login-title {
    text-align: center;
    font-size: 1.45rem;
    font-weight: 700;
    color: #1c2430;
    margin: 0 0 0.15rem 0;
}
.login-subtitle {
    text-align: center;
    font-size: 0.85rem;
    color: #7a8194;
    margin: 0 0 1.4rem 0;
}

/* --- Minimalist underline inputs ---------------------------------------- */
[data-testid="stForm"] [data-baseweb="input"] {
    border: none;
    border-bottom: 1.5px solid #d7dbe4;
    border-radius: 0;
    background: transparent;
    transition: border-color 0.2s ease;
}
[data-testid="stForm"] [data-baseweb="input"]:focus-within {
    border-bottom: 1.5px solid #8C72A3;
    box-shadow: none;
}
[data-testid="stForm"] [data-baseweb="input"] input {
    background: transparent;
    color: #1c2430;
    padding-left: 0.1rem;
}
[data-testid="stForm"] [data-baseweb="input"] input::placeholder {
    color: #9aa1b2;
}

/* --- Dark, rounded, professional submit button --------------------------- */
[data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
    background: #1c2430;
    color: #ffffff;
    border: none;
    border-radius: 999px;
    padding: 0.65rem 0;
    font-weight: 600;
    font-size: 1rem;
    margin-top: 1.1rem;
    transition: background 0.2s ease, transform 0.1s ease;
}
[data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover {
    background: #2b3648;
    color: #ffffff;
    transform: translateY(-1px);
}
[data-testid="stForm"] [data-testid="stFormSubmitButton"] button:active {
    transform: translateY(0);
}
</style>
"""


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

    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 1.05, 1])
    with center:
        with st.form("login_form"):
            st.markdown(
                f'<div class="login-logo">{_LOGO_SVG}</div>'
                '<h1 class="login-title">צוות AI וחדשנות</h1>'
                '<p class="login-subtitle">דשבורד ניהול משימות</p>',
                unsafe_allow_html=True,
            )
            username = st.text_input(
                "שם משתמש", placeholder="שם משתמש", label_visibility="collapsed"
            )
            password = st.text_input(
                "סיסמה", type="password", placeholder="סיסמה",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("כניסה", use_container_width=True, type="primary")

        if submitted:
            try:
                if _verify(username.strip(), password):
                    user = db.get_user(username.strip())
                    st.session_state["user"] = user["username"]
                    st.session_state["role"] = user["role"]
                    st.rerun()
                else:
                    st.error("שם משתמש או סיסמה שגויים. נסו שוב.")
            except psycopg2.OperationalError as exc:
                st.error(f"אין חיבור למסד הנתונים — בדקו את .streamlit/secrets.toml.\n\n{exc}")
    return False


def logout() -> None:
    for key in list(st.session_state.keys()):
        if key in ("user", "role", "view", "task_done_override", "_pending_writes") or str(
            key
        ).startswith("optimistic_"):
            st.session_state.pop(key, None)
    st.rerun()
