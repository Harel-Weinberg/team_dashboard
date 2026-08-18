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

/* Keep the "urgent" checkbox in the task bar tight and vertically centred. */
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stCheckbox"] label {
    margin-bottom: 0;
    white-space: nowrap;
}

/* Urgency level pill, shown under the urgency dropdown and inside the
   home-screen urgent-tasks widget. Traffic-light palette: green/amber/red
   reads instantly regardless of language. */
.urgency-pill {
    display: inline-block;
    border-radius: 999px;
    padding: 0.05rem 0.55rem;
    margin-inline-end: 0.3rem;
    font-size: 0.7rem;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
}
.urgency-pill.urgency-low    { background: #e8f7ee; color: #137a3f; }
.urgency-pill.urgency-medium { background: #fff4e0; color: #a8620a; }
.urgency-pill.urgency-high   { background: #fdecec; color: #c0202f; }

/* Status pill, used only in the home-screen urgent widget (the task-board
   card itself uses the interactive dropdown, not a static pill). */
.task-status-pill {
    display: inline-block;
    background: rgba(35, 33, 58, 0.07);
    color: #23213a;
    border-radius: 999px;
    padding: 0.05rem 0.55rem;
    margin-inline-end: 0.3rem;
    font-size: 0.7rem;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
}

/* Small blue "unread" badge — chat tab label, task-comments expander,
   urgent-tasks widget. Apple's system blue, not the app's Apple-blue accent
   (#0a84ff) used for primary actions, so an unread signal never looks like
   a clickable button. */
.unread-badge {
    display: inline-block;
    background: #007AFF;
    color: #ffffff;
    border-radius: 999px;
    padding: 0.05rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0, 122, 255, 0.35);
}

/* List-view header row above the task cards. Same column widths as the
   cards themselves (see ui_components.TASK_ROW_COLUMNS), styled as quiet
   column labels rather than another card. */
[class*="st-key-task_list_header"] {
    padding: 0 1.25rem;
    margin-bottom: 0.35rem;
}
.task-col-header {
    font-size: 0.72rem;
    font-weight: 700;
    color: #7a8194;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}

/* Status-filter multiselect pills: Apple-style vibrant green instead of
   Streamlit's default red/coral accent (this app has no [theme] section in
   .streamlit/config.toml, so multiselect tags fall back to Streamlit's own
   default primaryColor). Scoped to this one filter, not a global theme
   override, so other widgets keep the app's usual blue accent. */
[class*="st-key-task_status_filter_"] [data-baseweb="tag"] {
    background-color: #28a745 !important;
    border-color: #28a745 !important;
}
[class*="st-key-task_status_filter_"] [data-baseweb="tag"] span {
    color: #ffffff !important;
}

/* Task board revamp: Apple-style task cards ------------------------------ */

/* The "add task" form is collapsed by default (it grew too tall to leave
   open) — styled like a premium button-card rather than a generic
   expander: bigger radius matching the task cards below it, a visible
   shadow, and a lift-on-hover so the collapsed header reads as clickable.
   [data-testid="stExpander"] already strips the harsh default border and
   neutralizes the form nested inside; this narrows to just this expander
   and turns the shared look up a notch since it's the primary action on
   the page, not an incidental detail like the per-task comments expander. */
[class*="st-key-add_task_expander_"] {
    border-radius: 24px !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.07) !important;
    transition: box-shadow 0.2s ease, transform 0.2s ease;
}
[class*="st-key-add_task_expander_"]:has(summary:hover) {
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.10) !important;
    transform: translateY(-1px);
}
[class*="st-key-add_task_expander_"] summary {
    padding: 0.15rem 0;
}
[class*="st-key-add_task_expander_"] summary p {
    font-weight: 700;
    font-size: 1.02rem;
}

/* Each task card: white surface, generous radius, soft shadow — matching
   every other card in the app (sidebar, project bubbles, urgent widget). */
[class*="st-key-task_card_"] {
    background: rgba(255, 255, 255, 0.92);
    border-radius: 24px;
    padding: 1.1rem 1.25rem 0.6rem;
    margin-bottom: 0.85rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
    backdrop-filter: blur(10px);
}
/* A task still syncing to the server reads as a lighter, pending version of
   the same card, consistent with how chat/comments mute an in-flight send. */
[class*="st-key-task_card_pending_"] {
    opacity: 0.7;
}

/* Tag pills next to the task title. Fixed vocabulary -> fixed palette, so
   they read at a glance; anything outside the vocabulary (defensive only —
   the form only offers these four) falls back to a neutral grey pill. */
.task-tag {
    display: inline-block;
    border-radius: 999px;
    padding: 0.05rem 0.5rem;
    margin-inline-end: 0.3rem;
    font-size: 0.7rem;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
}
.task-tag.tag-frontend { background: #e0f0ff; color: #0a5cad; }
.task-tag.tag-backend  { background: #eee5ff; color: #5b3aa8; }
.task-tag.tag-bug      { background: #fdecec; color: #c0202f; }
.task-tag.tag-feature  { background: #e8f7ee; color: #137a3f; }
.task-tag.tag-default  { background: rgba(35, 33, 58, 0.08); color: #6b7280; }

/* Add-task form: the "הוספה" submit button turns solid, vivid green on
   hover — a distinct "this commits the task" affordance, deliberately not
   the app's Apple-blue primary color used everywhere else. */
[class*="st-key-add_task_submit_"] button:hover {
    background: #28a745 !important;
    color: #ffffff !important;
    border-color: transparent !important;
    box-shadow: 0 6px 18px rgba(40, 167, 69, 0.35);
}

/* Task comments, rendered with the same bubbles as the project chat tab.
   A pending (not-yet-synced) comment is muted the same way a pending chat
   send is — see the chatpend_ rule below, which this mirrors exactly. */
[class*="st-key-taskcommentpend_"] {
    opacity: 0.6;
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

/* Project bubble cards. The card is now the wrapping keyed container (rich
   HTML content: title, creator, activity summary) with a slim "open" button
   underneath — button labels can't carry colored/grey text, only a small
   markdown subset, so the rich part moved out of the button entirely. */
[class*="st-key-card_bubble_"] {
    background: #ffffff;
    border-radius: 24px;
    padding: 1.3rem 1.35rem 1.1rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
    position: relative;
    transition: transform 0.18s ease, box-shadow 0.18s ease;
}
[class*="st-key-card_bubble_"]:hover {
    transform: translateY(-4px);
    box-shadow: 0 16px 36px rgba(0, 0, 0, 0.10);
}
/* Gradient accent bar at the top of every bubble (matches the brand logo). */
[class*="st-key-card_bubble_"]::before {
    content: "";
    position: absolute;
    top: 0;
    right: 1.6rem;
    left: 1.6rem;
    height: 4px;
    border-radius: 0 0 4px 4px;
    background: linear-gradient(90deg, #4FB5CC 0%, #8C72A3 55%, #A71E85 100%);
    opacity: 0.7;
}
.project-bubble-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #23213a;
    margin-bottom: 0.25rem;
}
.project-bubble-meta {
    font-size: 0.8rem;
    color: #7a8194;
}
/* The activity summary line requested as "subtle grey text under created by". */
.project-activity-line {
    font-size: 0.8rem;
    color: #9aa1b2;
    margin-top: 0.3rem;
}
[class*="st-key-card_bubble_"] [data-testid="stButton"] button {
    margin-top: 0.9rem;
    border-radius: 999px;
    background: rgba(35, 33, 58, 0.06);
    color: #23213a;
    border: none;
    box-shadow: none;
    font-size: 0.85rem;
}
[class*="st-key-card_bubble_"] [data-testid="stButton"] button:hover {
    background: #0a84ff;
    color: #ffffff;
}

/* Urgent-tasks widget: white Apple card holding one mini-card per task. */
.st-key-urgent_widget {
    background: #ffffff;
    border: none;
    border-radius: 24px;
    padding: 1.15rem 1.25rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}
[class*="st-key-urgent_card_"] {
    background: rgba(255, 59, 48, 0.045);
    border-radius: 16px;
    padding: 0.7rem 0.95rem;
    margin-bottom: 0.55rem;
    transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
[class*="st-key-urgent_card_"]:hover {
    background: rgba(255, 59, 48, 0.09);
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(255, 59, 48, 0.12);
}
.urgent-card-title {
    font-weight: 700;
    color: #23213a;
    margin-bottom: 0.2rem;
}
.urgent-card-meta {
    font-size: 0.8rem;
    color: #7a8194;
}
[class*="st-key-urgent_card_"] [data-testid="stButton"] button {
    margin-top: 0.5rem;
    width: auto;
    border-radius: 999px;
    background: #ffffff;
    color: #23213a;
    border: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    font-size: 0.78rem;
    padding: 0.2rem 0.8rem;
    min-height: 0;
}
[class*="st-key-urgent_card_"] [data-testid="stButton"] button:hover {
    background: #0a84ff;
    color: #ffffff;
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
