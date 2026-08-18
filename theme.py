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

/* Light, airy pastel canvas: icy blue -> pale lavender -> clean white.
   Cards sit on top as stark WHITE surfaces lifted by soft shadows, so the
   hierarchy reads instantly (background = canvas, white = interactive). */
.stApp {
    background:
        radial-gradient(circle at 12% 8%, rgba(79, 181, 204, 0.13) 0%, rgba(79, 181, 204, 0) 40%),
        radial-gradient(circle at 90% 90%, rgba(167, 30, 133, 0.06) 0%, rgba(167, 30, 133, 0) 45%),
        linear-gradient(180deg, #e9f2fb 0%, #f2eefa 48%, #fbfcfe 100%);
}

/* Deep, highly readable purple-black text. */
[data-testid="stMain"] .block-container,
[data-testid="stSidebar"],
[data-testid="stMain"] h1, [data-testid="stMain"] h2,
[data-testid="stMain"] h3, [data-testid="stMain"] h4 {
    color: #23213a;
}

[data-testid="stMain"] .block-container {
    padding-top: 3.4rem;
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

/* Markdown, captions and alerts. */
[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"],
[data-testid="stAlert"] {
    direction: rtl;
    text-align: right;
}

/* Tab bar starts from the right. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    direction: rtl;
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

/* Sidebar: clean white panel lifted by a shadow (no border). */
[data-testid="stSidebar"] {
    background: #ffffff;
    border-inline-start: none;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}
[data-testid="stSidebarContent"] {
    padding: 0.7rem 0.5rem;
}

/* Buttons: fully rounded white pills — no borders, shadow for lift. */
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stFormSubmitButton"] button {
    border-radius: 999px;
    border: none;
    background: #ffffff;
    color: #23213a;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stFormSubmitButton"] button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.10);
    color: #23213a;
}
/* Primary buttons / selected nav: Apple blue pill. */
[data-testid="stBaseButton-primary"] {
    background: #0a84ff !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 999px;
    box-shadow: 0 6px 18px rgba(10, 132, 255, 0.32);
}
[data-testid="stBaseButton-primary"]:hover {
    background: #339dff !important;
}

/* Inputs & selects: rounded white, hairline-free (shadow instead of border). */
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stMain"] [data-baseweb="textarea"] {
    border-radius: 14px;
    background: #ffffff;
    border-color: transparent;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}
[data-testid="stChatInput"] {
    border-radius: 16px;
    background: #ffffff;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

/* Project chat: fixed-height scroll panel + iMessage-style bubbles.
   See ui_components._chat_bubble_html() — the row is forced to
   `direction: ltr` there so flex-start/flex-end are the LITERAL left/right
   edge of the screen, independent of the app's ambient RTL; the bubble
   itself is set back to `direction: rtl` so Hebrew still reads correctly. */
[class*="st-key-chat_scroll_"] {
    background: rgba(255, 255, 255, 0.55);
    border-radius: 20px;
    padding: 0.75rem 1rem 0.25rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.05);
    backdrop-filter: blur(10px);
}
.chat-row {
    display: flex;
    direction: ltr;
    margin: 0 0 0.5rem;
}
.chat-row.mine { justify-content: flex-start; }
.chat-row.theirs { justify-content: flex-end; }
.chat-bubble {
    max-width: 74%;
    padding: 0.55rem 0.9rem;
    border-radius: 18px;
    direction: rtl;
    text-align: right;
    unicode-bidi: isolate;
}
.chat-bubble-body {
    font-size: 0.95rem;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
}
.chat-bubble-meta {
    font-size: 0.7rem;
    margin-top: 0.25rem;
    opacity: 0.8;
    unicode-bidi: plaintext;
}
/* Mine: solid Apple-blue bubble, white text — the app's one existing accent
   color (see the primary-button rule above), so chat matches the rest of
   the UI's palette instead of introducing a second brand color. */
.chat-bubble.mine {
    background: #0a84ff;
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(10, 132, 255, 0.28);
}
.chat-bubble.mine .chat-bubble-meta { color: rgba(255, 255, 255, 0.85); }
/* Theirs: clean glass-white card with a soft shadow, matching every other
   card surface in the app. */
.chat-bubble.theirs {
    background: rgba(255, 255, 255, 0.9);
    color: #23213a;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
    backdrop-filter: blur(6px);
}
.chat-bubble.theirs .chat-bubble-meta { color: #6b7280; }

/* Tabs: iOS-style segmented control (pill track, white selected pill). */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: rgba(35, 33, 58, 0.06);
    border-radius: 999px;
    padding: 4px;
    gap: 4px;
    width: fit-content;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    border-radius: 999px;
    padding: 0.35rem 1.0rem;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: #ffffff;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.10);
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    display: none;
}

/* Expanders (task notes): white rounded cards. */
[data-testid="stExpander"] {
    border-radius: 16px;
    border: none;
    background: #ffffff;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
    overflow: hidden;
}
[data-testid="stExpander"] details {
    border: none;
}
/* Forms nested inside cards must not stack another card on top. */
[data-testid="stExpander"] [data-testid="stForm"] {
    background: transparent;
    box-shadow: none;
    padding: 0;
}

/* Tables. */
[data-testid="stDataFrame"] {
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
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
    color: #23213a;
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
    color: #23213a;
    margin: 1.1rem 0 0.9rem 0;
    text-align: right;
    direction: rtl;
}

/* Floating project bubbles (scoped to the bubbles container only). */
.st-key-project_bubbles [data-testid="stButton"] button {
    direction: rtl;
    width: 100%;
    min-height: 116px;
    padding: 1.4rem 1.35rem 1.2rem;
    border: none;
    border-radius: 24px;
    background: #ffffff;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
    color: #23213a;
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
    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.12);
    color: #23213a;
}
.st-key-project_bubbles [data-testid="stButton"] button:active {
    transform: translateY(-2px);
}
.st-key-project_bubbles [data-testid="stButton"] button p {
    text-align: right;
    width: 100%;
    margin: 0;
}

/* Urgent-tasks widget: white Apple card with red-tinted mini-card rows. */
.st-key-urgent_widget {
    background: #ffffff;
    border: none;
    border-radius: 24px;
    padding: 1.15rem 1.25rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}
.st-key-urgent_widget [data-testid="stButton"] button {
    direction: rtl;
    width: 100%;
    background: rgba(255, 59, 48, 0.055);
    border: none;
    border-radius: 16px;
    padding: 0.6rem 0.95rem;
    text-align: right;
    justify-content: flex-start;
    white-space: normal;
    line-height: 1.45;
    color: #23213a;
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
/* --- Chat: messages still in flight ------------------------------------- */
/* st.container(key=...) emits an st-key-<key> class. Pending sends are muted
   just enough to read as "in flight"; failed ones use a different key prefix
   and stay at full opacity so the retry control is not easy to miss. */
[class*="st-key-chatpend_"] {
    opacity: 0.6;
    transition: opacity 0.25s ease;
}

</style>
"""


def inject_app_css() -> None:
    """Inject the global RTL + Apple-style stylesheet (idempotent per rerun)."""
    st.markdown(APP_CSS, unsafe_allow_html=True)
