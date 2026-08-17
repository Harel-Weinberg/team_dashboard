"""
theme.py — Global look & feel: full RTL (Hebrew) layout + project bubble cards.

inject_app_css() is called once per rerun from main.py, after login. It:
  * flips the whole interface to right-to-left and keeps the sidebar on the
    right-hand side,
  * keeps inherently LTR content (timestamps, code) readable,
  * styles the welcome screen's project bubbles.

CSS for the project bubbles is scoped to the `.st-key-project_bubbles`
container so it can never leak into other buttons (sidebar nav, forms, etc.).
"""

import streamlit as st

APP_CSS = """
<style>
/* =======================================================================
   1. Global RTL layout
   ======================================================================= */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stSidebar"],
[data-testid="stSidebarContent"],
[data-testid="stHeader"] {
    direction: rtl;
}

[data-testid="stMain"] .block-container,
[data-testid="stSidebar"] {
    text-align: right;
}

/* Sidebar on the RIGHT.
   NOTE: `direction: rtl` on the flex app container already reverses the
   visual order of its children (sidebar + main), which puts the sidebar on
   the right. Do NOT also set `flex-direction: row-reverse` — the two
   cancel each other out and the sidebar snaps back to the left. */
[data-testid="stSidebar"] > div {
    direction: rtl;
}
/* Sidebar collapse / expand control follows the sidebar to the right. */
[data-testid="stSidebarCollapsedControl"] {
    right: 0.6rem !important;
    left: auto !important;
}

/* Inputs, textareas, selects and forms read right-to-left. */
[data-testid="stMain"] input,
[data-testid="stMain"] textarea,
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stChatInput"] textarea,
[data-testid="stForm"] {
    direction: rtl;
    text-align: right;
}
/* Typed text and placeholders follow their own language (so an English
   placeholder keeps its trailing "..." on the right side of the words). */
[data-testid="stMain"] input, [data-testid="stMain"] textarea,
[data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea,
[data-testid="stChatInput"] textarea {
    unicode-bidi: plaintext;
}

/* Headings, captions, markdown, alerts, tabs, expanders, chat bubbles. */
h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"],
[data-testid="stAlert"],
[data-testid="stExpander"] summary,
[data-testid="stChatMessageContent"] {
    direction: rtl;
    text-align: right;
}

/* Tab bar starts from the right. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    direction: rtl;
}

/* Chat rows: `direction: rtl` already puts the avatar on the right — no
   flex-direction override here either (see the sidebar note above). */
[data-testid="stChatMessage"] {
    text-align: right;
}

/* Mixed Hebrew/English UI: let every text run pick its own direction, so
   trailing punctuation (":", "...", "(0)") stays on the correct side.
   NOTE: `unicode-bidi` is NOT an inherited property — it has to be set on
   the elements that actually hold the text, not just on their containers. */
[data-testid="stMain"] p, [data-testid="stMain"] span,
[data-testid="stMain"] li, [data-testid="stMain"] small,
[data-testid="stMain"] h1, [data-testid="stMain"] h2,
[data-testid="stMain"] h3, [data-testid="stMain"] h4,
[data-testid="stMain"] label, [data-testid="stMain"] summary,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] li, [data-testid="stSidebar"] small,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] label {
    unicode-bidi: plaintext;
}

/* Content that must stay left-to-right to stay readable. */
code, pre, [data-testid="stDataFrame"] {
    direction: ltr;
    text-align: left;
}

/* Completed tasks: struck through (inline <s>) and dimmed. */
.task-done {
    opacity: 0.5;
    color: #6b7280;
}

/* =======================================================================
   2. Welcome screen — personalized greeting
   ======================================================================= */
.welcome-greeting {
    font-size: 2.1rem;
    font-weight: 700;
    color: #1c2430;
    margin: 0.2rem 0 0.1rem 0;
    text-align: right;
}
.welcome-sub {
    font-size: 1rem;
    color: #7a8194;
    margin: 0 0 1.6rem 0;
    text-align: right;
}
.welcome-section-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #1c2430;
    margin: 0.6rem 0 0.9rem 0;
    text-align: right;
}

/* =======================================================================
   3. Floating project bubbles (scoped to the bubbles container only)
   ======================================================================= */
.st-key-project_bubbles [data-testid="stButton"] button,
.st-key-project_bubbles button[data-testid="stBaseButton-secondary"] {
    direction: rtl;
    width: 100%;
    min-height: 116px;
    padding: 1.25rem 1.2rem 1.1rem;
    border: 1px solid rgba(140, 114, 163, 0.16);
    border-radius: 20px;
    background: linear-gradient(150deg, #ffffff 0%, #fbfaff 100%);
    box-shadow: 0 10px 26px rgba(60, 60, 120, 0.10);
    color: #1c2430;
    font-size: 1.05rem;
    font-weight: 600;
    text-align: right;
    align-items: flex-start;
    justify-content: center;
    white-space: normal;
    line-height: 1.5;
    transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

/* Gradient accent bar at the top of every bubble (matches the brand logo). */
.st-key-project_bubbles [data-testid="stButton"] {
    position: relative;
}
.st-key-project_bubbles [data-testid="stButton"]::before {
    content: "";
    position: absolute;
    top: 0;
    right: 1.4rem;
    left: 1.4rem;
    height: 4px;
    border-radius: 0 0 4px 4px;
    background: linear-gradient(90deg, #4FB5CC 0%, #8C72A3 55%, #A71E85 100%);
    opacity: 0.85;
    z-index: 1;
    pointer-events: none;
}

/* Floating hover effect. */
.st-key-project_bubbles [data-testid="stButton"] button:hover {
    transform: translateY(-6px);
    box-shadow: 0 20px 40px rgba(60, 60, 120, 0.18);
    border-color: rgba(140, 114, 163, 0.42);
    color: #1c2430;
}
.st-key-project_bubbles [data-testid="stButton"] button:active {
    transform: translateY(-2px);
}
.st-key-project_bubbles [data-testid="stButton"] button p {
    text-align: right;
    width: 100%;
    margin: 0;
}
</style>
"""


def inject_app_css() -> None:
    """Inject the global RTL + bubble stylesheet (idempotent per rerun)."""
    st.markdown(APP_CSS, unsafe_allow_html=True)
