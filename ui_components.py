"""
ui_components.py — All reusable UI pieces (Hebrew / RTL interface):

* render_sidebar()            — home button, navigation, projects hub, new project
* render_project_dashboard()  — spec / tasks / chat tabs for one project
* render_task_board()         — reusable task list (also powers urgent & backlog)
* render_adhoc_board()        — urgent tasks / future backlog pages
* render_welcome()            — personalized greeting + floating project bubbles
* render_pending_project()    — placeholder while a new project syncs to the DB

Write operations follow the Optimistic UI pattern (see optimistic.py): the
change appears instantly from st.session_state while the database write runs
on a background thread; failed syncs surface as warnings and the UI falls
back to database truth.
"""

import html
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitAPIException

import auth
import database as db
import notifications
import optimistic
import perf

LOCAL_TZ = ZoneInfo("Asia/Jerusalem")

# Distinct avatars so each user is instantly recognizable in the chat feed.
AVATARS = {"Harel": "🔵", "Yitzhak": "🟢"}
DEFAULT_AVATAR = "⚪"


def fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _resolve_pending_projects() -> list[dict]:
    """Swap optimistic project entries for their real DB rows once the insert lands."""
    pending = st.session_state.get("optimistic_projects", [])
    for entry in list(pending):
        future = entry["future"]
        if not future.done():
            continue
        pending.remove(entry)
        selected_here = st.session_state.get("view") == ("pending_project", entry["temp_id"])
        if future.exception() is not None:  # warning shown by report_sync_failures
            if selected_here:
                st.session_state["view"] = None
            continue
        new_id = future.result()
        if new_id is None:
            st.warning(f"פרויקט בשם '{entry['name']}' כבר קיים.")
            if selected_here:
                st.session_state["view"] = None
        elif selected_here:
            st.session_state["view"] = ("project", new_id)
    st.session_state["optimistic_projects"] = pending
    return pending


def _rerun_scoped() -> None:
    """Rerun just the enclosing fragment, falling back to a full rerun.

    Streamlit only accepts scope="fragment" while it is actually running a
    fragment rerun. The same code path also executes during a full script run
    (first paint, or any rerun triggered from outside the fragment), and asking
    for fragment scope there raises. Try the cheap option, take the correct one.
    """
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def go_home() -> None:
    """Clear the selected project and return to the main (bubbles) screen."""
    st.session_state["view"] = None


@perf.track("sidebar")
def render_sidebar():
    """Render navigation. Returns the current view: ('project', id) | ('pending_project', temp_id) | 'urgent' | 'backlog' | 'users' | None."""
    user = st.session_state["user"]

    with st.sidebar:
        st.markdown("## 🚀 צוות AI וחדשנות")
        st.caption(f"{AVATARS.get(user, DEFAULT_AVATAR)} מחובר/ת: **{user}**")

        # --- Home ---------------------------------------------------------
        on_home = st.session_state.get("view") is None
        if st.button(
            "🏠 דף הבית",
            key="nav_home",
            use_container_width=True,
            type="primary" if on_home else "secondary",
            help="חזרה למסך הראשי עם כל הפרויקטים",
        ):
            go_home()
            st.rerun()

        # No manual refresh button: chat polls itself every 3s and the task
        # caches expire on their own, so there is nothing left for the user to
        # force.
        if st.button("🚪 יציאה", use_container_width=True):
            auth.logout()

        st.divider()

        # --- Projects hub -------------------------------------------------
        st.markdown("### 📁 הפרויקטים שלנו")
        pending_projects = _resolve_pending_projects()
        projects = db.get_projects()
        if not projects and not pending_projects:
            st.caption("עדיין אין פרויקטים — הוסיפו אחד למטה.")
        for project in projects:
            is_selected = st.session_state.get("view") == ("project", project["id"])
            if st.button(
                f"📂 {project['name']}",
                key=f"nav_project_{project['id']}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state["view"] = ("project", project["id"])
                st.rerun()
        for entry in pending_projects:
            is_selected = st.session_state.get("view") == ("pending_project", entry["temp_id"])
            if st.button(
                f"🕓 {entry['name']}",
                key=f"nav_pending_{entry['temp_id']}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state["view"] = ("pending_project", entry["temp_id"])
                st.rerun()

        # --- New project ----------------------------------------------------
        with st.form("add_project_form", clear_on_submit=True, border=False):
            new_name = st.text_input(
                "פרויקט חדש",
                placeholder="שם פרויקט חדש...",
                label_visibility="collapsed",
                key="new_project_name",
            )
            if st.form_submit_button("➕ פרויקט חדש", use_container_width=True):
                name = new_name.strip()
                if not name:
                    st.warning("נא להזין שם פרויקט.")
                else:
                    temp_id = uuid.uuid4().hex
                    future = optimistic.submit_write(
                        f"פרויקט '{name}'", db.add_project, name, user
                    )
                    st.session_state.setdefault("optimistic_projects", []).append(
                        {"temp_id": temp_id, "name": name, "future": future}
                    )
                    st.session_state["view"] = ("pending_project", temp_id)
                    st.rerun()

        st.divider()

        # --- Standalone pages ----------------------------------------------
        pages = [("🔥 משימות דחופות", "urgent"), ("💡 רעיונות לעתיד", "backlog")]
        if auth.is_admin():
            pages.append(("👥 ניהול משתמשים", "users"))
        for label, view_key in pages:
            is_selected = st.session_state.get("view") == view_key
            if st.button(
                label,
                key=f"nav_{view_key}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state["view"] = view_key
                st.rerun()

    return st.session_state.get("view")


# ---------------------------------------------------------------------------
# Module A — Product specification
# ---------------------------------------------------------------------------


@perf.track("spec")
def _render_spec(project_id: int):
    user = st.session_state["user"]
    spec = db.get_spec(project_id)

    content = st.text_area(
        "אפיון הפרויקט, הלוגיקה והמוצר — נכתב במשותף:",
        value=spec["content"],
        height=420,
        key=f"spec_text_{project_id}",
        placeholder="תארו את המוצר, הלוגיקה, התהליכים ומקרי הקצה...",
    )
    if st.button("💾 שמירת האפיון", type="primary", key=f"spec_save_{project_id}"):
        db.save_spec(project_id, content, user)
        st.rerun()

    if spec["updated_by"]:
        st.caption(f"*עודכן לאחרונה על ידי **{spec['updated_by']}** ב-{fmt_ts(spec['updated_at'])}*")
    else:
        st.caption("*עדיין לא נשמר.*")


# ---------------------------------------------------------------------------
# Module B — Task board (shared by projects, urgent and backlog)
# ---------------------------------------------------------------------------


def _set_task_status(task: dict, new_status: str):
    """Optimistically switch a task's status and sync in the background.

    Trigger 2: on an open -> completed transition, notify the task's creator.
    Same edge as before ('בוצע' is the only status that maps to is_done).
    """
    user = st.session_state["user"]
    future = optimistic.submit_write(
        "סטטוס משימה", db.set_task_status, task["id"], new_status, user
    )
    st.session_state.setdefault("task_status_override", {})[task["id"]] = {
        "value": new_status,
        "future": future,
    }

    was_done = task.get("status") == db.STATUS_DONE
    if new_status == db.STATUS_DONE and not was_done:
        toast = notifications.notify_task_completed(task["created_by"], task["title"], user)
        if toast:
            # Shown on the rerun that follows this callback (see main.py).
            st.session_state["pending_toast"] = toast


def _on_status_change(widget_key: str, task: dict):
    """on_change handler for a task's status selectbox."""
    _set_task_status(task, st.session_state[widget_key])


def _set_task_urgency(task: dict, new_level: str):
    """Optimistically switch a task's urgency level and sync in the background."""
    future = optimistic.submit_write(
        "רמת דחיפות", db.set_task_urgency, task["id"], new_level
    )
    st.session_state.setdefault("task_urgency_override", {})[task["id"]] = {
        "value": new_level,
        "future": future,
    }


def _on_urgency_change(widget_key: str, task: dict):
    """on_change handler for a task's urgency selectbox."""
    _set_task_urgency(task, st.session_state[widget_key])


def _effective_urgency(task: dict) -> tuple[str, bool]:
    """Return (urgency level to display, whether an optimistic override is in flight)."""
    overrides = st.session_state.setdefault("task_urgency_override", {})
    override = overrides.get(task["id"])
    if override is not None:
        future = override["future"]
        landed = task.get("urgency") == override["value"]
        if future.done() and (future.exception() is not None or landed):
            overrides.pop(task["id"])  # failed (revert to DB truth) or confirmed
            override = None
    if override is not None:
        return override["value"], True
    return task.get("urgency") or db.URGENCY_MEDIUM, False


def _effective_status(task: dict) -> tuple[str, bool]:
    """Return (status to display, whether an optimistic override is in flight)."""
    overrides = st.session_state.setdefault("task_status_override", {})
    override = overrides.get(task["id"])
    if override is not None:
        future = override["future"]
        landed = task.get("status") == override["value"]
        if future.done() and (future.exception() is not None or landed):
            overrides.pop(task["id"])  # failed (revert to DB truth) or confirmed
            override = None
    if override is not None:
        return override["value"], True
    return task.get("status") or db.STATUS_IN_PROGRESS, False


def _mail_icon_html(mailto: str | None, is_done: bool) -> str:
    """Minimalist 📧 link that opens the user's mail client with a ready draft.

    Returns "" when the recipient has no email on file, so the icon is hidden.
    """
    if not mailto:
        return ""
    tooltip = "שליחת מייל על סיום המשימה" if is_done else "שליחת התראה במייל לאחראי/ת"
    # html.escape() turns the query separator '&' into '&amp;' — required for a
    # valid href attribute; the browser decodes it back when following the link.
    return (
        f'<a class="task-mail" href="{html.escape(mailto, quote=True)}" '
        f'title="{tooltip}" aria-label="{tooltip}">📧</a>'
    )


# Fixed tag vocabulary (not free text) so every tag can get a deterministic
# color — the pills are meant to read at a glance, which a per-user palette
# of arbitrary strings couldn't guarantee.
DEFAULT_TAGS = ["Front-End", "Back-End", "Bug", "Feature"]
TAG_CSS_CLASS = {
    "Front-End": "tag-frontend",
    "Back-End": "tag-backend",
    "Bug": "tag-bug",
    "Feature": "tag-feature",
}

# Attachments are stored as bytes in Postgres (see database.py) — capped here
# so a large upload can't bloat the primary OLTP database or the connection
# pool. Generous enough for a screenshot or a short PDF, nothing more.
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _tag_pills_html(tags: list[str] | None) -> str:
    if not tags:
        return ""
    return "".join(
        f'<span class="task-tag {TAG_CSS_CLASS.get(tag, "tag-default")}">'
        f"{html.escape(tag)}</span>"
        for tag in tags
    )


def _fmt_date(value) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)  # defensive: an ISO string that _revive() didn't reach


def _task_meta_line(task_or_echo: dict) -> str:
    """👤 assignee · 📅 due date — both optional. Used by the pending-task
    row, which (having no columns to align with a header) keeps the old
    compact single-line format instead of _render_task's per-column layout.
    """
    parts = []
    assignee = task_or_echo.get("assignee")
    if assignee:
        parts.append(f"👤 {html.escape(assignee)}")
    due = _fmt_date(task_or_echo.get("due_date"))
    if due:
        parts.append(f"📅 {due}")
    return " · ".join(parts)


URGENCY_CSS_CLASS = {
    db.URGENCY_LOW: "urgency-low",
    db.URGENCY_MEDIUM: "urgency-medium",
    db.URGENCY_HIGH: "urgency-high",
}


def _urgency_pill_html(level: str) -> str:
    css_class = URGENCY_CSS_CLASS.get(level, "urgency-medium")
    return f'<span class="urgency-pill {css_class}">{html.escape(level)}</span>'


def _task_title_html(title: str, is_done: bool, tags: list[str] | None = None) -> str:
    """Task name: tag pills, then bold/struck-through title.

    Urgency has its own dedicated column in the list-view layout (see
    _render_task) rather than an inline pill here.
    """
    safe_title = html.escape(title)
    parts = []
    tag_html = _tag_pills_html(tags)
    if tag_html:
        parts.append(tag_html)
    parts.append(f"<s>{safe_title}</s>" if is_done else f"<strong>{safe_title}</strong>")
    body = " ".join(parts)
    if is_done:
        body = f'<span class="task-done">{body}</span>'
    return body


def _unread_badge_html(count: int) -> str:
    """Small blue unread-count badge. Empty string at count<=0 — never show
    a badge for zero, per the explicit "only when unread > 0" requirement."""
    if count <= 0:
        return ""
    return f'<span class="unread-badge">🔵 {count}</span>'


# A short sine-wave "ping" synthesized with the Web Audio API rather than an
# embedded audio file — no binary asset to ship, and the envelope (linear
# ramp up/down instead of a hard on/off) avoids the audible click a raw
# on/off gain change would produce.
_PING_JS = """
<script>
(function() {
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = new Ctx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0.16, ctx.currentTime + 0.02);
        gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.22);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.25);
    } catch (e) {
        // Web Audio unavailable, or the browser's autoplay policy is
        // blocking sound before any user gesture on the page — fail
        // silently rather than surface a JS error in a hidden iframe.
    }
})();
</script>
"""


def _play_ping_if_increased(session_key: str, current_count: int) -> None:
    """Play a short ping the instant `current_count` rises above what this
    session last saw for `session_key` — purely a comparison against
    st.session_state, run inside whatever render already happened to fire
    (a full rerun on navigation, or an existing fragment's own poll tick).
    No timer, interval or new st.fragment is created for this: it rides
    whichever refresh cycle was already going to run for other reasons.

    Silent on the very first observation of a key: a pre-existing unread
    backlog seen at login is not a "new" arrival, and silent on any
    decrease (that's a read, not a message arriving).
    """
    baseline = st.session_state.setdefault("unread_ping_baseline", {})
    previous = baseline.get(session_key)
    baseline[session_key] = current_count
    if previous is not None and current_count > previous:
        components.html(_PING_JS, height=0)


def _mark_scope_viewed(scope_type: str, scope_id: int, items: list[dict]) -> None:
    """Debounced read-receipt update for a project chat or task-comments scope.

    Writes only when the newest item is newer than what this session already
    marked read for this scope — without that, a 500ms/1s poll tick would
    re-upsert last_read_at every single tick regardless of whether anything
    new arrived, which is exactly the "infinite loop" of writes the original
    request calls out to avoid. `items` must be sorted oldest-first (both
    get_chat() and get_comments_map() already are).

    One limitation, stated plainly rather than hidden: st.tabs (in the mode
    this app uses) and st.expander both compute their content unconditionally
    regardless of whether they're the visually selected/open one, so this
    can't distinguish "the user is looking at this exact tab/expander" from
    "this project is open at all in this session". "Unread" here means
    "arrived since this scope was last processed while the project/task
    board was open", which is coarser than true view-tracking but is the
    honest limit of what these widgets expose without switching them to
    lazy (on_change="rerun") rendering — a bigger change than asked for here.
    """
    if not items:
        return
    newest = items[-1].get("created_at")
    if newest is None:
        return
    marked = st.session_state.setdefault("read_marked_through", {})
    key = (scope_type, scope_id)
    if marked.get(key) == newest:
        return
    marked[key] = newest
    user = st.session_state["user"]
    optimistic.submit_write("עדכון סטטוס קריאה", db.mark_scope_read, user, scope_type, scope_id)


# List-view column layout: status | urgency | name+tags+description |
# assignee | due date | email. Used by both the header row and every task
# card so they align exactly.
TASK_ROW_COLUMNS = [0.13, 0.13, 0.34, 0.15, 0.15, 0.10]
TASK_ROW_HEADERS = ["סטטוס משימה", "דחיפות", "שם המשימה", "מפתח אחראי", "תאריך יעד", "מייל"]


def _render_task_header():
    """Column headers above the task list — st.columns with the exact same
    widths as _render_task, so header and card cells line up."""
    with st.container(key="task_list_header"):
        for col, label in zip(st.columns(TASK_ROW_COLUMNS), TASK_ROW_HEADERS):
            col.markdown(f'<div class="task-col-header">{label}</div>', unsafe_allow_html=True)


def _render_task(task: dict, comments: list[dict], unread_comments: int = 0):
    """An Apple-style list row: status/urgency dropdowns, name+tags+
    description, assignee, due date and a mailto icon — six columns aligned
    with _render_task_header — plus attachment/comments below, all inside
    one keyed container (also what lets theme.py give it rounded corners
    and a shadow). A still-in-flight status/urgency change isn't muted here:
    unlike chat, a task write has no "failed, please retry" UI, matching the
    pre-existing philosophy for every other task write in this file, so
    there's no separate muted/failed visual state to drive from the Future).
    """
    user = st.session_state["user"]
    status, status_syncing = _effective_status(task)
    is_done = status == db.STATUS_DONE
    urgency, urgency_syncing = _effective_urgency(task)
    status_key = f"task_status_{task['id']}"
    urgency_key = f"task_urgency_{task['id']}"

    # If another user changed the task in the DB, let the DB value win.
    if status_key in st.session_state and st.session_state[status_key] != status:
        del st.session_state[status_key]
    if urgency_key in st.session_state and st.session_state[urgency_key] != urgency:
        del st.session_state[urgency_key]

    with st.container(key=f"task_card_{task['id']}"):
        status_col, urgency_col, name_col, assignee_col, date_col, mail_col = st.columns(
            TASK_ROW_COLUMNS, vertical_alignment="top"
        )
        with status_col:
            st.selectbox(
                "סטטוס", db.TASK_STATUSES,
                index=db.TASK_STATUSES.index(status),
                key=status_key, label_visibility="collapsed",
                # No manual rerun here — Streamlit already reruns the
                # enclosing fragment once after an on_change callback
                # returns; calling _rerun_scoped() too would just be a
                # second, redundant rerun, not a loop, but there's no
                # reason to pay for it. Same idiom for urgency below.
                on_change=_on_status_change, args=(status_key, task),
                help="שינוי סטטוס המשימה",
            )
        with urgency_col:
            st.selectbox(
                "דחיפות", db.TASK_URGENCY_LEVELS,
                index=db.TASK_URGENCY_LEVELS.index(urgency),
                key=urgency_key, label_visibility="collapsed",
                on_change=_on_urgency_change, args=(urgency_key, task),
                help="שינוי רמת הדחיפות",
            )
            st.markdown(_urgency_pill_html(urgency), unsafe_allow_html=True)
        with name_col:
            st.markdown(_task_title_html(task["title"], is_done, task.get("tags")),
                        unsafe_allow_html=True)
            if task.get("description"):
                st.caption(task["description"])
        with assignee_col:
            if task.get("assignee"):
                st.markdown(f"👤 {html.escape(task['assignee'])}")
        with date_col:
            due = _fmt_date(task.get("due_date"))
            if due:
                st.markdown(f"📅 {due}")
        with mail_col:
            mailto = notifications.build_mailto_link(task, is_done=is_done)
            st.markdown(_mail_icon_html(mailto, is_done), unsafe_allow_html=True)

        meta = f"נוצר על ידי {task['created_by']} · {fmt_ts(task['created_at'])}"
        if status_syncing or urgency_syncing:
            meta += " · 🕓 מסתנכרן…"
        elif is_done and task["completed_by"]:
            meta += f" · ✅ בוצע על ידי {task['completed_by']} ב-{fmt_ts(task['completed_at'])}"
        st.caption(meta)

        if task.get("attachment_name"):
            fetched = db.get_task_attachment(task["id"])
            if fetched:
                name, mime, data = fetched
                st.download_button(
                    "📎 הורדת קובץ מצורף", data=data, file_name=name,
                    mime=mime or "application/octet-stream",
                    key=f"task_attachment_dl_{task['id']}",
                )

        comment_echoes = st.session_state.setdefault("optimistic_comments", {})
        pending_comments = optimistic.surviving_echoes(
            comment_echoes.get(task["id"], []),
            landed=lambda e: any(
                c["author"] == e["author"] and c["content"] == e["content"] for c in comments
            ),
        )
        comment_echoes[task["id"]] = pending_comments

        badge = _unread_badge_html(unread_comments)
        label = f"💬 הערות ({len(comments) + len(pending_comments)})"
        with st.expander(label):
            if badge:
                st.markdown(badge, unsafe_allow_html=True)
            _mark_scope_viewed(db.SCOPE_TASK_COMMENTS, task["id"], comments)
            # The exact same bubble markup as the project chat tab —
            # rendered per-comment (not batched) since this list is short
            # and some rows need their own muted-while-pending container.
            for comment in comments:
                st.markdown(
                    _chat_bubble_html(
                        comment["author"], fmt_ts(comment["created_at"]),
                        comment["content"], is_mine=comment["author"] == user,
                    ),
                    unsafe_allow_html=True,
                )
            for i, echo in enumerate(pending_comments):
                with st.container(key=f"taskcommentpend_{task['id']}_{i}"):
                    st.markdown(
                        _chat_bubble_html(
                            echo["author"], "שולח…", echo["content"], is_mine=True,
                        ),
                        unsafe_allow_html=True,
                    )

            with st.form(f"comment_form_{task['id']}", clear_on_submit=True, border=False):
                note = st.text_area(
                    "הוספת הערה למשימה",
                    height=80,
                    placeholder="כתבו הערה על המשימה הזו...",
                    key=f"comment_text_{task['id']}",
                    label_visibility="collapsed",
                )
                if st.form_submit_button("💬 שמירת הערה"):
                    text = note.strip()
                    if text:
                        future = optimistic.submit_write(
                            "הערה למשימה", db.add_comment, task["id"], text, user
                        )
                        comment_echoes.setdefault(task["id"], []).append(
                            {"author": user, "content": text, "future": future}
                        )
                        _rerun_scoped()

            # Deleting stays synchronous on purpose: destructive actions
            # should confirm against the DB before the row disappears.
            if st.button("🗑️ מחיקת המשימה", key=f"task_delete_{task['id']}"):
                db.delete_task(task["id"])
                st.rerun()


def _render_pending_task(echo: dict, index: int):
    # No interactive controls yet — the row has no database id until it syncs,
    # so the container key is just this render's position in the pending list.
    with st.container(key=f"task_card_pending_{index}"):
        status_col, body_col = st.columns([0.22, 0.78], vertical_alignment="center")
        status_col.markdown("🕓")
        with body_col:
            urgency_pill = _urgency_pill_html(
                db.URGENCY_HIGH if echo.get("is_urgent") else db.URGENCY_MEDIUM
            )
            st.markdown(
                urgency_pill + " " + _task_title_html(echo["title"], False, echo.get("tags")),
                unsafe_allow_html=True,
            )
            if echo.get("description"):
                st.caption(echo["description"])
            meta = _task_meta_line(echo)
            st.caption(f"{meta} · מסתנכרן עם מסד הנתונים…" if meta else "מסתנכרן עם מסד הנתונים…")


# Reconciliation (surviving_echoes / _effective_status / _effective_urgency
# below) only re-evaluates when this fragment executes. Without a poll, a
# background write that resolves while the user isn't clicking anything else
# in this board would sit at "מסתנכרן…" until some unrelated interaction
# happened to rerun it. The check itself is nearly free when nothing is
# pending — get_tasks()/get_comments_map() are cache hits for 30s
# (VOLATILE_TTL) at a time, so most of these ticks touch no database at all.
TASK_BOARD_POLL = "1s"


def _task_matches_filters(
    item: dict, query: str, only_mine: bool, user: str, selected_statuses: list[str],
) -> bool:
    """Shared predicate for both landed tasks and pending echoes — both
    support the same .get() surface (title/description/assignee/status)."""
    if query:
        q = query.strip().lower()
        haystack = f"{item.get('title') or ''} {item.get('description') or ''}".lower()
        if q not in haystack:
            return False
    if only_mine and item.get("assignee") != user:
        return False
    # Pending echoes have no `status` yet — a task always starts "in progress".
    if (item.get("status") or db.STATUS_IN_PROGRESS) not in selected_statuses:
        return False
    return True


def _render_task_filters(scope: str, user: str) -> tuple[str, bool, list[str], bool]:
    """The search/filter bar above the task list. Returns the current filter
    state; _task_board_fragment applies it to both tasks and pending echoes.
    """
    search_col, mine_col = st.columns([0.7, 0.3], vertical_alignment="center")
    with search_col:
        query = st.text_input(
            "חיפוש משימות", placeholder="🔍 חיפוש לפי כותרת או תיאור...",
            label_visibility="collapsed", key=f"task_search_{scope}",
        )
    with mine_col:
        only_mine = st.toggle("המשימות שלי", key=f"task_mine_{scope}")

    status_col, sort_col = st.columns([0.75, 0.25], vertical_alignment="center")
    with status_col:
        selected_statuses = st.multiselect(
            "סינון לפי סטטוס", db.TASK_STATUSES, default=list(db.TASK_STATUSES),
            label_visibility="collapsed", key=f"task_status_filter_{scope}",
        )
    with sort_col:
        sort_by_due = st.checkbox(
            "📅 מיון לפי תאריך יעד", key=f"task_sort_due_{scope}",
            help="מיון המשימות המוצגות לפי התאריך הקרוב ביותר",
        )
    return query, only_mine, selected_statuses, sort_by_due


def render_task_board(project_id: int | None = None, task_type: str = "project"):
    """Public entry point; the body runs inside a fragment.

    A checkbox, an urgency toggle or an add-task submit therefore re-renders
    only this board — not the sidebar, the header, the theme injection and the
    other two tabs. The poll keeps that isolation: it reruns this fragment
    only (never scope="app"), so an in-flight write resolving on its own
    still can't force a full-page rerender.
    """
    _task_board_fragment(project_id, task_type)


@st.fragment(run_every=TASK_BOARD_POLL)
@perf.track("tasks")
def _task_board_fragment(project_id: int | None, task_type: str):
    # A fragment-scoped rerun never re-enters main(), so drain here too:
    #
    # add_task/set_task_status/set_task_urgent/add_comment run on a background
    # worker thread. Per the E6 thread-discipline rule, a worker can't call
    # st.cache_data.clear() itself — db._invalidate() queues the clear instead
    # and only main() used to drain it. Without this line, the poll below
    # would dutifully rerun every second and read the SAME stale cached
    # bundle each time (until VOLATILE_TTL expired on its own), because the
    # write that made it stale never got applied. That combination — queued
    # invalidation, no drain point reachable from a fragment-only rerun — was
    # the actual bug: the fix isn't "make a background write trigger a
    # rerun", it's "make sure a rerun (however it happens) can see the write".
    db.drain_deferred_invalidations()
    user = st.session_state["user"]
    # A fragment-scoped rerun never re-enters main(), so drain the toast queue
    # here as well — otherwise a completion/urgency toast would not appear
    # until some later full rerun.
    if toast := st.session_state.pop("pending_toast", None):
        st.toast(toast)
    scope = f"{task_type}_{project_id if project_id is not None else 'global'}"
    echo_key = f"optimistic_tasks_{scope}"

    # --- Add a task ---------------------------------------------------------
    # Collapsed by default: the form covers everything a task can carry
    # (details, due date, tags, an attachment) and got big enough that
    # leaving it open by default ate too much screen space above the list.
    with st.expander(
        "➕ הוספת משימה חדשה", expanded=False, key=f"add_task_expander_{scope}"
    ):
        # Spacious, one field per row with the label above it, rather than the
        # old compact single-row layout.
        with st.form(f"add_task_form_{scope}", clear_on_submit=True, border=False):
            st.markdown("**כותרת המשימה**")
            title = st.text_input(
                "כותרת המשימה", placeholder="משימה חדשה...",
                label_visibility="collapsed", key=f"task_title_{scope}",
            )

            st.markdown("**פירוט המשימה**")
            description = st.text_area(
                "פירוט המשימה", placeholder="תיאור מפורט של המשימה...", height=90,
                label_visibility="collapsed", key=f"task_description_{scope}",
            )

            dev_col, due_col = st.columns(2)
            with dev_col:
                st.markdown("**מפתח**")
                assignee = st.selectbox(
                    "מפתח", db.get_users(), label_visibility="collapsed",
                    key=f"task_assignee_{scope}",
                )
            with due_col:
                st.markdown("**תאריך יעד**")
                due_date = st.date_input(
                    "תאריך יעד", value=None, label_visibility="collapsed",
                    key=f"task_due_{scope}",
                )

            st.markdown("**תגיות**")
            tags = st.multiselect(
                "תגיות", DEFAULT_TAGS, label_visibility="collapsed",
                key=f"task_tags_{scope}",
            )

            st.markdown("**קובץ מצורף**")
            uploaded = st.file_uploader(
                "קובץ מצורף", type=["png", "jpg", "jpeg", "pdf"],
                label_visibility="collapsed", key=f"task_attachment_{scope}",
            )

            is_urgent = st.checkbox(
                "🔥 דחוף", key=f"task_urgent_{scope}", help="סימון המשימה כדחופה"
            )

            submitted = st.form_submit_button(
                "הוספה", use_container_width=True, key=f"add_task_submit_{scope}",
            )
            if submitted:
                text = title.strip()
                if not text:
                    st.warning("יש להזין כותרת למשימה.")
                else:
                    attachment = None
                    if uploaded is not None:
                        data = uploaded.getvalue()
                        if len(data) > MAX_ATTACHMENT_BYTES:
                            st.error(
                                f"הקובץ '{uploaded.name}' גדול מ-"
                                f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB ולא נשמר."
                            )
                        else:
                            attachment = (uploaded.name, uploaded.type, data)
                    future = optimistic.submit_write(
                        f"משימה '{text}'", db.add_task, text, assignee, user,
                        project_id, task_type, is_urgent,
                        description=description.strip(), due_date=due_date,
                        tags=tags, attachment=attachment,
                    )
                    st.session_state.setdefault(echo_key, []).append({
                        "title": text, "assignee": assignee, "created_by": user,
                        "is_urgent": is_urgent, "description": description.strip(),
                        "due_date": due_date, "tags": tags, "future": future,
                    })
                    # Trigger 1: a new urgent task notifies its assignee.
                    if is_urgent and assignee:
                        st.session_state["pending_toast"] = notifications.notify_urgent_assignment(
                            assignee, text
                        )
                    _rerun_scoped()

    # --- Task list -----------------------------------------------------------
    tasks = db.get_tasks(project_id=project_id, task_type=task_type)
    pending_tasks = optimistic.surviving_echoes(
        st.session_state.get(echo_key, []),
        landed=lambda e: any(
            t["title"] == e["title"] and t["created_by"] == e["created_by"] for t in tasks
        ),
    )
    st.session_state[echo_key] = pending_tasks

    if not tasks and not pending_tasks:
        st.info("אין משימות עדיין — הוסיפו את הראשונה למעלה.")
        return

    query, only_mine, selected_statuses, sort_by_due = _render_task_filters(scope, user)

    def matches(item):
        return _task_matches_filters(item, query, only_mine, user, selected_statuses)

    visible_tasks = [t for t in tasks if matches(t)]
    visible_pending = [e for e in pending_tasks if matches(e)]
    if sort_by_due:
        # NULLs (no due date) sort last regardless of direction.
        visible_tasks = sorted(
            visible_tasks, key=lambda t: (t.get("due_date") is None, t.get("due_date"))
        )

    open_count = len([t for t in tasks if not t["is_done"]]) + len(pending_tasks)
    total_count = len(tasks) + len(pending_tasks)
    visible_count = len(visible_tasks) + len(visible_pending)
    caption = f'{open_count} פתוחות · {total_count} סה"כ'
    if visible_count != total_count:
        caption += f" · מוצגות {visible_count}"
    st.caption(caption)

    if not visible_tasks and not visible_pending:
        st.caption("אין משימות התואמות את הסינון הנוכחי.")
        return

    comments_map = db.get_comments_map(project_id=project_id, task_type=task_type)
    unread_map = db.get_task_comment_unread_counts(user, project_id=project_id, task_type=task_type)
    _render_task_header()
    for task in visible_tasks:
        _render_task(task, comments_map.get(task["id"], []), unread_map.get(task["id"], 0))
    for i, echo in enumerate(visible_pending):
        _render_pending_task(echo, i)


# ---------------------------------------------------------------------------
# Module C — Project chat (live + optimistic send)
# ---------------------------------------------------------------------------

# Must stay LONGER than database.CHAT_TTL / WATERMARK_TTL, or the poll only
# re-serves cache.
CHAT_POLL = "500ms"


def _pending_chat(project_id: int) -> list[dict]:
    """This session's messages that have not yet come back from the server."""
    return st.session_state.setdefault("pending_msgs", {}).setdefault(project_id, [])


def _dispatch_chat_write(project_id: int, entry: dict) -> None:
    """(Re)send one pending message on the background pool.

    The insert is idempotent on client_msg_id, so retrying after an ambiguous
    failure cannot double-post.
    """
    entry["future"] = optimistic.submit_write(
        "הודעה בצ'אט",
        db.add_chat_message,
        project_id,
        entry["body"],
        entry["sender"],
        entry["client_msg_id"],
    )


CHAT_SCROLL_HEIGHT = 500


def _chat_bubble_html(sender: str, when: str, body: str, *, is_mine: bool) -> str:
    """One message as a self-contained, iMessage-style HTML bubble.

    Layout direction (which side the bubble sits on) and text direction
    (how the Hebrew inside it reads) are two different concerns that must be
    set separately: the row is forced to `direction: ltr` so `flex-start`
    always means the literal left edge of the screen regardless of the app's
    RTL context — inheriting the ambient `direction: rtl` here would flip
    "mine"/"theirs" to the wrong sides. The bubble's own content is then set
    back to `direction: rtl` so Hebrew still reads correctly inside it.
    """
    side = "mine" if is_mine else "theirs"
    avatar = AVATARS.get(sender, DEFAULT_AVATAR)
    safe_body = html.escape(body)
    safe_sender = html.escape(sender or "")
    return (
        f'<div class="chat-row {side}">'
        f'<div class="chat-bubble {side}">'
        f'<div class="chat-bubble-body">{safe_body}</div>'
        f'<div class="chat-bubble-meta">{avatar} {safe_sender} · {when}</div>'
        "</div></div>"
    )


def _on_chat_viewed(project_id: int, messages: list[dict]) -> None:
    """Debounced read-receipt update for this project's chat — see
    _mark_scope_viewed for the debounce mechanics and its one caveat."""
    _mark_scope_viewed(db.SCOPE_PROJECT_CHAT, project_id, messages)


def _watermarked_messages(project_id: int) -> list[dict]:
    """Full message list, refetched only when the chat's watermark has moved.

    get_chat_watermark() is a tiny index-only MAX(created_at) probe; get_chat()
    is a real SELECT * ... LIMIT. Paying for the cheap one on every 500ms tick
    and the expensive one only when something in this project's chat actually
    changed is what keeps 500ms polling affordable per connected user.
    """
    seen = st.session_state.setdefault("chat_watermark_seen", {})
    cached = st.session_state.setdefault("chat_last_messages", {})
    watermark = db.get_chat_watermark(project_id)
    if project_id not in cached or seen.get(project_id) != watermark:
        cached[project_id] = db.get_chat(project_id)
        seen[project_id] = watermark
    return cached[project_id]


def _promote_confirmed(pending: list[dict]) -> bool:
    """Mark entries whose background write has resolved successfully.

    A resolved, exception-free Future already proves the row is committed —
    the unique index on client_msg_id makes the insert idempotent, so there is
    nothing left to verify by waiting for the row to come back from a read.
    Visual state is driven from here, NOT from whether the id has appeared in
    a fresh db.get_chat() read (that check only ever removes duplicates once
    the server row is loaded — see the "landed" filter below).

    Returns True the first time any entry gets promoted this run, so the
    caller can force an immediate, uncached refetch instead of waiting for
    CHAT_TTL or the next poll tick.
    """
    newly_confirmed = False
    for entry in pending:
        future = entry.get("future")
        if future is None or not future.done() or future.exception() is not None:
            continue
        if not entry.get("confirmed"):
            entry["confirmed"] = True
            newly_confirmed = True
    return newly_confirmed


@st.fragment(run_every=CHAT_POLL)
@perf.track("chat")
def _chat_fragment(project_id: int):
    """The whole chat panel, isolated from the rest of the page.

    Being a fragment is what makes polling affordable: every poll tick this
    re-runs on its own, so a teammate's message appears without a click and
    without re-rendering the sidebar, the header or the other two tabs.
    """
    user = st.session_state["user"]
    pending = _pending_chat(project_id)

    # A send that just succeeded jumps straight to full opacity instead of
    # waiting out CHAT_TTL / the next poll tick: force one uncached refetch
    # right now, before rendering, so this same tick already shows the real
    # row (dropped from `pending` below) instead of a transient
    # "confirmed but still a local echo" frame.
    if _promote_confirmed(pending):
        db.get_chat.clear()
        db.get_chat_watermark.clear()
        st.session_state.get("chat_watermark_seen", {}).pop(project_id, None)
        st.session_state.get("chat_last_messages", {}).pop(project_id, None)
        _rerun_scoped()

    messages = _watermarked_messages(project_id)

    # Reconcile: drop any echo whose id has come back from the server. This
    # only prevents duplicate rendering — it never drives opacity/failed state
    # (that comes from the Future itself, in _promote_confirmed above).
    landed = {m["client_msg_id"] for m in messages if m.get("client_msg_id")}
    pending = [e for e in pending if e["client_msg_id"] not in landed]
    st.session_state["pending_msgs"][project_id] = pending

    # Fixed-height, independently scrolling panel — the page itself no longer
    # grows with the conversation. autoscroll=True keeps it anchored to the
    # newest message (both on first open and as new ones arrive), matching
    # standard chat apps: oldest at the top, newest at the bottom.
    with st.container(
        height=CHAT_SCROLL_HEIGHT, border=False, autoscroll=True,
        key=f"chat_scroll_{project_id}",
    ):
        if not messages and not pending:
            st.caption("אין הודעות עדיין — כתבו את הראשונה למטה 👇")

        if messages:
            # Landed messages have no interactivity, so they're batched into
            # one markdown call instead of one st element per row — cheaper
            # for the frontend to diff on every 500ms poll tick. Oldest first,
            # so the newest lands at the bottom.
            st.markdown(
                "".join(
                    _chat_bubble_html(
                        m["sender"], fmt_ts(m["created_at"]), m["message"],
                        is_mine=m["sender"] == user,
                    )
                    for m in messages
                ),
                unsafe_allow_html=True,
            )

        # Pending sends are always more recent than any landed row, so they
        # render last (at the bottom, below every real message) — oldest
        # pending first, same as the real-message ordering above.
        for entry in pending:
            future = entry.get("future")
            failed = future is not None and future.done() and future.exception() is not None
            # Keyed containers get an st-key-* class in the DOM; theme.py
            # mutes only the still-in-flight ones. Confirmed and failed
            # entries render at full opacity — a failure needs attention, and
            # a confirmed send is (transiently) as good as landed.
            if failed:
                key_prefix = "chatfail"
            elif entry.get("confirmed"):
                key_prefix = "chatconfirmed"
            else:
                key_prefix = "chatpend"
            with st.container(key=f"{key_prefix}_{entry['client_msg_id']}"):
                st.markdown(
                    _chat_bubble_html(
                        entry["sender"], fmt_ts(entry["created_at"]), entry["body"],
                        is_mine=entry["sender"] == user,
                    ),
                    unsafe_allow_html=True,
                )
                if failed:
                    # Never silently drop a message the user watched appear.
                    st.caption(f"⚠️ ההודעה לא נשלחה — {future.exception()}")
                    if st.button("↻ שליחה חוזרת", key=f"retry_{entry['client_msg_id']}"):
                        entry["confirmed"] = False
                        _dispatch_chat_write(project_id, entry)
                        _rerun_scoped()

    # Computed BEFORE _on_chat_viewed marks this batch read, so the ping
    # sees the genuinely-unread count for this tick, not the just-cleared
    # one — same query the tab-label badge uses, riding this fragment's
    # own existing 500ms poll rather than a timer of its own.
    _play_ping_if_increased(
        f"chat_tab_{project_id}", db.get_chat_unread_counts(user).get(project_id, 0)
    )
    _on_chat_viewed(project_id, messages)

    if prompt := st.chat_input("כתבו הודעה לצוות...", key=f"chat_input_{project_id}"):
        text = prompt.strip()
        if text:
            entry = {
                "client_msg_id": str(uuid.uuid4()),
                "sender": user,
                "body": text,
                "created_at": datetime.now(LOCAL_TZ),
                "confirmed": False,
            }
            _dispatch_chat_write(project_id, entry)
            _pending_chat(project_id).append(entry)
            _rerun_scoped()


def _render_chat(project_id: int):
    _chat_fragment(project_id)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@perf.track("project_page")
def render_project_dashboard(project: dict):
    # Fill every cache this page reads in one parallel burst (~1 round-trip of
    # wall-clock) instead of letting the tabs fetch sequentially.
    db.warm_project(project["id"], wait=True)

    st.title(f"📂 {project['name']}")
    st.caption(f"נוצר על ידי {project['created_by']} · {fmt_ts(project['created_at'])}")

    # Spec is the home tab for every project. Without a per-project key,
    # st.tabs is one widget instance shared across every project dashboard
    # (same call site, same labels) — the frontend keeps whichever tab index
    # you last clicked, so opening a different project from the "Chat" tab of
    # a previous one landed you straight back on "Chat". Keying by project id
    # makes each project's tabs a distinct widget: switching projects mounts
    # a fresh instance, which starts on `default` regardless of what was
    # selected in the last one.
    # Computed before st.tabs so the badge doesn't depend on which tab body
    # actually executes: label content doesn't affect the widget's identity
    # (that's `key=` below), so updating it on every render can't reset the
    # tab selection back to `default`.
    user = st.session_state["user"]
    chat_unread = db.get_chat_unread_counts(user).get(project["id"], 0)
    _play_ping_if_increased(f"chat_tab_{project['id']}", chat_unread)
    chat_label = "💬 תקשורת צוות"
    if chat_unread > 0:
        chat_label += f" **🔵 {chat_unread}**"

    tab_labels = ["📋 אפיון המוצר", "✅ משימות פיתוח", chat_label]
    spec_tab, tasks_tab, chat_tab = st.tabs(
        tab_labels,
        key=f"project_tabs_{project['id']}",
        default=tab_labels[0],
    )
    with spec_tab:
        _render_spec(project["id"])
    with tasks_tab:
        render_task_board(project_id=project["id"], task_type="project")
    with chat_tab:
        _render_chat(project["id"])


def render_pending_project(temp_id: str):
    """Placeholder while a new project's insert is in flight; auto-advances when done."""
    entry = next(
        (e for e in st.session_state.get("optimistic_projects", []) if e["temp_id"] == temp_id),
        None,
    )
    if entry is None:  # resolved (or failed) elsewhere — go home
        st.session_state["view"] = None
        st.rerun()

    @st.fragment(run_every="0.5s")
    def _poll():
        if entry["future"].done():
            st.rerun(scope="app")  # sidebar resolver swaps this view for the real project
        st.info(f"🕓 יוצר את הפרויקט **{entry['name']}** — מסתנכרן עם מסד הנתונים…")

    _poll()


def render_adhoc_board(title: str, subtitle: str, task_type: str):
    st.title(title)
    st.caption(subtitle)
    render_task_board(project_id=None, task_type=task_type)


@perf.track("welcome")
def render_welcome():
    """Personalized greeting + floating project bubbles (main screen)."""
    user = st.session_state["user"]

    st.markdown(
        f'<div class="welcome-greeting">👋 ברוך הבא, {html.escape(user)}</div>'
        '<div class="welcome-sub">צוות AI וחדשנות · דשבורד ניהול משימות</div>',
        unsafe_allow_html=True,
    )

    # Critical items first: the urgent widget sits ABOVE the project bubbles so
    # open urgent tasks are the first thing the user sees after logging in.
    _render_urgent_widget()

    projects = db.get_projects()
    pending_projects = st.session_state.get("optimistic_projects", [])

    if not projects and not pending_projects:
        st.info("עדיין אין פרויקטים — הוסיפו פרויקט חדש מהסרגל הימני.")
        return

    st.markdown('<div class="welcome-section-title">📁 הפרויקטים שלנו</div>', unsafe_allow_html=True)

    # One query each for every project's activity summary, instead of one
    # query per project per bubble.
    chat_unread = db.get_chat_unread_counts(user)
    open_counts = db.get_open_task_counts()
    _play_ping_if_increased("home_total_chat_unread", sum(chat_unread.values()))

    def _activity_line(project_id: int) -> str:
        unread = chat_unread.get(project_id, 0)
        open_tasks = open_counts.get(project_id, 0)
        if not unread and not open_tasks:
            return ""
        bits = []
        if unread:
            bits.append(f"💬 {unread} הודעות חדשות")
        if open_tasks:
            bits.append(f"📌 {open_tasks} משימות פתוחות")
        return '<div class="project-activity-line">' + " | ".join(bits) + "</div>"

    # Rich HTML content (title, creator line, grey activity summary, tag-style
    # unread badge) can't live inside a single st.button — button labels only
    # support a small markdown subset (bold/italic/links), no raw HTML/color.
    # So each bubble is a keyed card with an HTML block on top and a slim
    # full-width "open" button underneath, matching the same pattern used
    # for the urgent-tasks widget below.
    bubbles = [
        {
            "html": (
                f'<div class="project-bubble-title">📂 <strong>{html.escape(p["name"])}</strong></div>'
                f'<div class="project-bubble-meta">נוצר על ידי {html.escape(p["created_by"] or "")} '
                f'· {fmt_ts(p["created_at"])}</div>'
                f'{_activity_line(p["id"])}'
            ),
            "key": f"bubble_project_{p['id']}",
            "view": ("project", p["id"]),
        }
        for p in projects
    ] + [
        {
            "html": (
                f'<div class="project-bubble-title">🕓 <strong>{html.escape(e["name"])}</strong></div>'
                '<div class="project-bubble-meta">נשמר כרגע במסד הנתונים…</div>'
            ),
            "key": f"bubble_pending_{e['temp_id']}",
            "view": ("pending_project", e["temp_id"]),
        }
        for e in pending_projects
    ]

    per_row = 3
    with st.container(key="project_bubbles"):
        for start in range(0, len(bubbles), per_row):
            row = bubbles[start : start + per_row]
            columns = st.columns(per_row, gap="medium")
            for column, bubble in zip(columns, row):
                with column:
                    with st.container(key=f"card_{bubble['key']}"):
                        st.markdown(bubble["html"], unsafe_allow_html=True)
                        if st.button(
                            "פתיחה ←", key=bubble["key"], use_container_width=True,
                        ):
                            st.session_state["view"] = bubble["view"]
                            st.rerun()

    st.caption(
        "כל שינוי מתועד עם השם והשעה ומסונכרן לענן — לחצו 🔄 רענון כדי לשלוף עדכונים מהצוות."
    )

    # Silently pre-warm every project's data in the background while the user
    # is looking at the home screen, so clicking a bubble feels instant.
    # Warm caches make this a no-op (microseconds), so calling it per rerun is safe.
    db.prefetch_all_projects()


def _render_urgent_widget():
    """Home-screen widget with every open urgent task across all projects,
    styled to match the internal task cards: status, tags, due date and an
    unread-comments badge — not just a bare title+source button label
    (button labels can't carry colored pills/badges, only plain markdown)."""
    urgent_tasks = db.get_urgent_open_tasks()
    if not urgent_tasks:
        return

    user = st.session_state["user"]
    unread_map = db.get_unread_counts_for_tasks(
        user, tuple(t["id"] for t in urgent_tasks)
    )

    st.markdown(
        f'<div class="welcome-section-title">🔥 משימות דחופות ({len(urgent_tasks)})</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="urgent_widget"):
        for task in urgent_tasks:
            source = task["project_name"] or (
                "משימות דחופות" if task["task_type"] == "urgent" else "רעיונות לעתיד"
            )
            status = task.get("status") or db.STATUS_IN_PROGRESS
            urgency = task.get("urgency") or db.URGENCY_HIGH
            due = _fmt_date(task.get("due_date"))
            badge = _unread_badge_html(unread_map.get(task["id"], 0))

            meta_bits = [f"📂 {html.escape(source)}"]
            if task["assignee"]:
                meta_bits.append(f"👤 {html.escape(task['assignee'])}")
            if due:
                meta_bits.append(f"📅 {due}")

            html_block = (
                f'<div class="urgent-card-title">{_urgency_pill_html(urgency)} '
                f'<span class="task-status-pill">{html.escape(status)}</span> '
                f'{_tag_pills_html(task.get("tags"))} '
                f'<strong>{html.escape(task["title"])}</strong>'
                f"{(' ' + badge) if badge else ''}</div>"
                f'<div class="urgent-card-meta">{" · ".join(meta_bits)}</div>'
            )
            with st.container(key=f"urgent_card_{task['id']}"):
                st.markdown(html_block, unsafe_allow_html=True)
                if st.button("פתיחה ←", key=f"urgent_widget_{task['id']}"):
                    if task["project_id"] is not None:
                        st.session_state["view"] = ("project", task["project_id"])
                    else:
                        st.session_state["view"] = task["task_type"]
                    st.rerun()
