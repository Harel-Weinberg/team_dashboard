"""
theme.py — Global look & feel: Apple-inspired design system + full RTL (Hebrew).

Design language (macOS/iOS):
  * generous border-radius — 24px cards/bubbles, 12px inputs/buttons,
    999px pills,
  * soft diffused shadows (0 4px 24px rgba(0,0,0,0.06)) instead of hard borders,
  * translucent "glass" surfaces with backdrop blur,
  * breathable whitespace and a native system font stack.

RTL notes:
  * `direction: rtl` on the app container both flips text and puts the sidebar
    on the right (never add flex-direction: row-reverse on top — they cancel).
  * Emojis must render to the RIGHT of Hebrew labels. Labels put the emoji
    first in the string; for that to land on the right the text run must
    resolve RTL even when the label contains Latin (e.g. a project named
    "AI Bot"), so buttons/tabs/headings get `direction: rtl` +
    `unicode-bidi: isolate` instead of `plaintext`.
  * Mixed Hebrew/number captions keep `unicode-bidi: plaintext` so counters
    like '3 פתוחות' don't reorder.

CSS for the project bubbles / urgent widget is scoped to `.st-key-*`
containers so it can never leak into other buttons.
"""

import streamlit as st

APP_CSS = """
<style>
/* =======================================================================
   0. Foundation — typography, background, whitespace
   ======================================================================= */
html, body, .stApp, [data-testid="stSidebar"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
                 "Heebo", "Helvetica Neue", Arial, sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 12% 10%, rgba(79, 181, 204, 0.10) 0%, rgba(79, 181, 204, 0) 42%),
        radial-gradient(circle at 88% 85%, rgba(167, 30, 133, 0.07) 0%, rgba(167, 30, 133, 0) 48%),
        linear-gradient(180deg, #f7f8fb 0%, #f1f2f7 100%);
}

[data-testid="stMain"] .block-container {
    padding-top: 3.2rem;
    padding-bottom: 4rem;
    max-width: 1120px;
}

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

/* Markdown, captions, alerts and chat bodies. */
[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"],
[data-testid="stAlert"],
[data-testid="stChatMessageContent"] {
    direction: rtl;
    text-align: right;
}

/* Tab bar starts from the right. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    direction: rtl;
}

/* Chat rows: `direction: rtl` already puts the avatar on the right. */
[data-testid="stChatMessage"] {
    text-align: right;
}

/* Content that must stay left-to-right to stay readable. */
code, pre, [data-testid="stDataFrame"] {
    direction: ltr;
    text-align: left;
}

/* Mixed Hebrew/English body text: let every text run pick its own direction,
   so trailing punctuation (":", "...", "(0)") stays on the correct side.
   NOTE: `unicode-bidi` is NOT inherited — it must sit on the text elements. */
[data-testid="stMain"] p, [data-testid="stMain"] span,
[data-testid="stMain"] li, [data-testid="stMain"] small,
[data-testid="stMain"] label, [data-testid="stMain"] summary,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] li, [data-testid="stSidebar"] small,
[data-testid="stSidebar"] label {
    unicode-bidi: plaintext;
}

/* Emoji placement: labels lead with the emoji, and forcing the run RTL makes
   that leading emoji render as the RIGHTMOST element — even when the rest of
   the label is Latin (project names, usernames). `isolate` keeps any inner
   English readable. Declared AFTER the plaintext block so it wins. */
[data-testid="stMain"] button p,
[data-testid="stSidebar"] button p,
[data-baseweb="tab"] p,
[data-testid="stExpander"] summary p,
[data-testid="stMain"] h1, [data-testid="stMain"] h2,
[data-testid="stMain"] h3, [data-testid="stMain"] h4,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    direction: rtl;
    unicode-bidi: isolate;
}

/* =======================================================================
   2. Apple-style components
   ======================================================================= */

/* Sidebar: frosted glass panel. */
[data-testid="stSidebar"] {
    background: rgba(255, 255, 255, 0.68);
    backdrop-filter: saturate(180%) blur(22px);
    -webkit-backdrop-filter: saturate(180%) blur(22px);
    border-inline-start: 1px solid rgba(0, 0, 0, 0.05);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
}
[data-testid="stSidebarContent"] {
    padding: 0.6rem 0.4rem;
}

/* Buttons: rounded, soft border, gentle hover lift. */
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stFormSubmitButton"] button {
    border-radius: 12px;
    border: 1px solid rgba(0, 0, 0, 0.07);
    background: rgba(255, 255, 255, 0.85);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stFormSubmitButton"] button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}
/* Primary buttons / selected nav: Apple blue. */
[data-testid="stBaseButton-primary"] {
    background: #0a84ff !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 12px;
    box-shadow: 0 4px 14px rgba(10, 132, 255, 0.30);
}
[data-testid="stBaseButton-primary"]:hover {
    background: #339dff !important;
}

/* Inputs & selects: rounded, translucent. */
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stMain"] [data-baseweb="textarea"],
[data-testid="stChatInput"] {
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.85);
    border-color: rgba(0, 0, 0, 0.08);
}

/* Tabs: iOS-style segmented control. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: rgba(120, 120, 128, 0.10);
    border-radius: 12px;
    padding: 3px;
    gap: 3px;
    width: fit-content;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    border-radius: 10px;
    padding: 0.35rem 0.9rem;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: #ffffff;
    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.12);
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    display: none;
}

/* Expanders (task notes): floating glass cards. */
[data-testid="stExpander"] {
    border-radius: 16px;
    border: 1px solid rgba(0, 0, 0, 0.05);
    background: rgba(255, 255, 255, 0.72);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
    overflow: hidden;
}
[data-testid="stExpander"] details {
    border: none;
}

/* Chat: message bubbles. */
[data-testid="stChatMessage"] {
    background: rgba(255, 255, 255, 0.78);
    border-radius: 18px;
    padding: 0.85rem 1.05rem;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
    margin-bottom: 0.45rem;
}
[data-testid="stChatInput"] {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}

/* Tables. */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}

/* Completed tasks: struck through (inline <s>) and dimmed. */
.task-done {
    opacity: 0.5;
    color: #6b7280;
}

/* Mail icon next to a task — a clear call-to-action (opens a mailto: draft). */
a.task-mail {
    text-decoration: none;
    display: inline-block;
    margin-inline-start: 0.55rem;
    padding: 0.1rem 0.35rem;
    border-radius: 10px;
    font-size: 1.5rem;
    line-height: 1;
    vertical-align: middle;
    opacity: 0.75;
    transition: opacity 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
a.task-mail:hover {
    opacity: 1;
    background: rgba(140, 114, 163, 0.14);
    transform: translateY(-1px);
    text-decoration: none;
}

/* --- Task row controls ---------------------------------------------------- */

/* Completed: prominent green pill (click to un-complete). */
[class*="st-key-task_undone_"] button {
    background: #e8f7ee !important;
    color: #137a3f !important;
    border: 1px solid rgba(19, 122, 63, 0.22) !important;
    border-radius: 999px !important;
    padding: 0.12rem 0.6rem;
    min-height: 0;
    font-size: 0.78rem;
    font-weight: 700;
    white-space: nowrap;
    box-shadow: 0 1px 6px rgba(19, 122, 63, 0.12);
}
[class*="st-key-task_undone_"] button:hover {
    background: #d7f0e2 !important;
    border-color: rgba(19, 122, 63, 0.5) !important;
}

/* Urgency toggle — active state: red pill. */
[class*="st-key-task_urgent_on_"] button {
    background: #fdecec !important;
    color: #c0202f !important;
    border: 1px solid rgba(192, 32, 47, 0.22) !important;
    border-radius: 999px !important;
    padding: 0.12rem 0.55rem;
    min-height: 0;
    font-size: 0.75rem;
    font-weight: 700;
    white-space: nowrap;
    box-shadow: 0 1px 6px rgba(192, 32, 47, 0.12);
}
[class*="st-key-task_urgent_on_"] button:hover {
    background: #fbdcdc !important;
    border-color: rgba(192, 32, 47, 0.5) !important;
}

/* Urgency toggle — inactive state: greyed-out, quiet until hovered. */
[class*="st-key-task_urgent_off_"] button {
    background: transparent !important;
    border: 1px dashed #d7dbe4 !important;
    border-radius: 999px !important;
    padding: 0.12rem 0.5rem;
    min-height: 0;
    font-size: 0.75rem;
    filter: grayscale(1);
    opacity: 0.45;
    box-shadow: none;
    transition: opacity 0.15s ease, filter 0.15s ease;
}
[class*="st-key-task_urgent_off_"] button:hover {
    opacity: 1;
    filter: grayscale(0);
    border-style: solid !important;
    border-color: rgba(192, 32, 47, 0.45) !important;
    transform: none;
}

/* Urgent tag inside a not-yet-synced task echo. */
.task-urgent {
    display: inline-block;
    background: #fdecec;
    color: #c0202f;
    border: 1px solid rgba(192, 32, 47, 0.28);
    border-radius: 999px;
    padding: 0.05rem 0.5rem;
    margin-inline-end: 0.35rem;
    font-size: 0.72rem;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
}

/* Keep the "urgent" checkbox in the task bar tight and vertically centred. */
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stCheckbox"] label {
    margin-bottom: 0;
    white-space: nowrap;
}

/* =======================================================================
   3. Welcome screen — greeting, bubbles, urgent widget
   ======================================================================= */
.welcome-greeting {
    font-size: 2.1rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #1c2430;
    margin: 0.2rem 0 0.1rem 0;
    text-align: right;
    direction: rtl;
}
.welcome-sub {
    font-size: 1rem;
    color: #7a8194;
    margin: 0 0 1.8rem 0;
    text-align: right;
    direction: rtl;
}
.welcome-section-title {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: #1c2430;
    margin: 1.1rem 0 0.9rem 0;
    text-align: right;
    direction: rtl;
}

/* Floating project bubbles (scoped to the bubbles container only). */
.st-key-project_bubbles [data-testid="stButton"] button {
    direction: rtl;
    width: 100%;
    min-height: 116px;
    padding: 1.35rem 1.3rem 1.15rem;
    border: 1px solid rgba(0, 0, 0, 0.04);
    border-radius: 24px;
    background: rgba(255, 255, 255, 0.82);
    backdrop-filter: saturate(180%) blur(18px);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
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
    right: 1.6rem;
    left: 1.6rem;
    height: 4px;
    border-radius: 0 0 4px 4px;
    background: linear-gradient(90deg, #4FB5CC 0%, #8C72A3 55%, #A71E85 100%);
    opacity: 0.7;
    z-index: 1;
    pointer-events: none;
}
.st-key-project_bubbles [data-testid="stButton"] button:hover {
    transform: translateY(-6px);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.12);
    border-color: rgba(0, 0, 0, 0.08);
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

/* Urgent-tasks widget: glass card with red-tinted mini-card rows. */
.st-key-urgent_widget {
    background: rgba(255, 255, 255, 0.75);
    backdrop-filter: saturate(180%) blur(18px);
    border: 1px solid rgba(255, 59, 48, 0.14);
    border-radius: 20px;
    padding: 1.05rem 1.15rem;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
}
.st-key-urgent_widget [data-testid="stButton"] button {
    direction: rtl;
    width: 100%;
    background: rgba(255, 59, 48, 0.05);
    border: 1px solid rgba(255, 59, 48, 0.10);
    border-radius: 14px;
    padding: 0.55rem 0.9rem;
    text-align: right;
    justify-content: flex-start;
    white-space: normal;
    line-height: 1.45;
    color: #1c2430;
    box-shadow: none;
    transition: transform 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.st-key-urgent_widget [data-testid="stButton"] button:hover {
    background: rgba(255, 59, 48, 0.10);
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(255, 59, 48, 0.12);
}
.st-key-urgent_widget [data-testid="stButton"] button p {
    text-align: right;
    width: 100%;
    margin: 0;
}
</style>
"""


def inject_app_css() -> None:
    """Inject the global RTL + Apple-style stylesheet (idempotent per rerun)."""
    st.markdown(APP_CSS, unsafe_allow_html=True)
