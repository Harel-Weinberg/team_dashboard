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


def _set_task_done(task: dict, new_value: bool):
    """Optimistically set a task's completion status and sync in the background.

    Trigger 2: on an open -> completed transition, notify the task's creator.
    """
    user = st.session_state["user"]
    future = optimistic.submit_write(
        "סטטוס משימה", db.set_task_done, task["id"], new_value, user
    )
    st.session_state.setdefault("task_done_override", {})[task["id"]] = {
        "value": new_value,
        "future": future,
    }

    if new_value and not task["is_done"]:  # only on the open -> completed edge
        toast = notifications.notify_task_completed(task["created_by"], task["title"], user)
        if toast:
            # Shown on the rerun that follows this callback (see main.py).
            st.session_state["pending_toast"] = toast


def _toggle_task(task_id: int, widget_key: str, task: dict):
    """on_change handler for the 'בוצע' checkbox of an open task."""
    _set_task_done(task, bool(st.session_state[widget_key]))


def _set_task_urgent(task: dict, new_value: bool):
    """Optimistically flip a task's urgent flag and sync in the background."""
    future = optimistic.submit_write(
        "סטטוס דחיפות", db.set_task_urgent, task["id"], new_value
    )
    st.session_state.setdefault("task_urgent_override", {})[task["id"]] = {
        "value": new_value,
        "future": future,
    }


def _effective_urgent(task: dict) -> bool:
    """Urgency to display: a pending local toggle wins until the DB confirms it."""
    overrides = st.session_state.setdefault("task_urgent_override", {})
    override = overrides.get(task["id"])
    if override is not None:
        future = override["future"]
        landed = bool(task.get("is_urgent")) == override["value"]
        if future.done() and (future.exception() is not None or landed):
            overrides.pop(task["id"])  # failed (revert to DB truth) or confirmed
            override = None
    return override["value"] if override else bool(task.get("is_urgent"))


def _effective_done(task: dict) -> tuple[bool, bool]:
    """Return (done-status to display, whether an optimistic override is in flight)."""
    overrides = st.session_state.setdefault("task_done_override", {})
    override = overrides.get(task["id"])
    if override is not None:
        future = override["future"]
        landed = bool(task["is_done"]) == override["value"]
        if future.done() and (future.exception() is not None or landed):
            overrides.pop(task["id"])  # failed (revert to DB truth) or confirmed
            override = None
    if override is not None:
        return override["value"], True
    return bool(task["is_done"]), False


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


def _task_title_html(
    title: str,
    assignee: str | None,
    is_done: bool,
    is_urgent: bool = False,
    mailto: str | None = None,
) -> str:
    """Task title: urgent tag first, bold when open, struck through + dimmed when done."""
    safe_title = html.escape(title)
    parts = []
    if is_urgent:
        parts.append('<span class="task-urgent">🔥 דחוף</span>')
    parts.append(f"<s>{safe_title}</s>" if is_done else f"<strong>{safe_title}</strong>")
    if assignee:
        parts.append(f"· 👤 <code>{html.escape(assignee)}</code>")
    body = " ".join(parts)
    # When completed, dim the whole line (tag and assignee included) — but keep
    # the mail link outside the dimmed wrapper so it stays clearly clickable.
    if is_done:
        body = f'<span class="task-done">{body}</span>'
    return body + _mail_icon_html(mailto, is_done)


def _render_task(task: dict, comments: list[dict]):
    user = st.session_state["user"]
    done_key = f"task_done_{task['id']}"
    is_done, syncing = _effective_done(task)

    # If another user changed the task in the DB, let the DB value win.
    if done_key in st.session_state and bool(st.session_state[done_key]) != is_done:
        del st.session_state[done_key]

    is_urgent = _effective_urgent(task)

    # Top-aligned so the status/urgency controls line up with the task title
    # rather than being centred against the title + metadata block.
    status_col, urgent_col, body_col = st.columns([0.12, 0.10, 0.78], vertical_alignment="top")
    with status_col:
        if is_done:
            # A prominent green "completed" pill that also un-completes on click,
            # so the action stays reversible without a second control.
            if st.button(
                "✅ הושלם",
                key=f"task_undone_{task['id']}",
                help="לחצו לביטול סימון הביצוע",
            ):
                _set_task_done(task, False)
                st.rerun()
        else:
            st.checkbox(
                "בוצע",
                value=is_done,
                key=done_key,
                label_visibility="collapsed",
                on_change=_toggle_task,
                args=(task["id"], done_key, task),
                help="סימון המשימה כבוצעה",
            )
    with urgent_col:
        # Interactive urgency toggle. Two distinct keys (on/off) so each state
        # can be styled independently in theme.py.
        if is_urgent:
            if st.button(
                "🔥 דחוף",
                key=f"task_urgent_on_{task['id']}",
                help="לחצו כדי לבטל את סימון הדחיפות",
            ):
                _set_task_urgent(task, False)
                st.rerun()
        elif st.button(
            "🔥",
            key=f"task_urgent_off_{task['id']}",
            help="לחצו כדי לסמן את המשימה כדחופה",
        ):
            _set_task_urgent(task, True)
            st.rerun()
    with body_col:
        st.markdown(
            _task_title_html(
                task["title"], task["assignee"], is_done,
                mailto=notifications.build_mailto_link(task, is_done=is_done),
            ),
            unsafe_allow_html=True,
        )

        meta = f"נוצר על ידי {task['created_by']} · {fmt_ts(task['created_at'])}"
        if syncing:
            meta += " · 🕓 מסתנכרן…"
        elif is_done and task["completed_by"]:
            meta += f" · ✅ בוצע על ידי {task['completed_by']} ב-{fmt_ts(task['completed_at'])}"
        st.caption(meta)

        comment_echoes = st.session_state.setdefault("optimistic_comments", {})
        pending_comments = optimistic.surviving_echoes(
            comment_echoes.get(task["id"], []),
            landed=lambda e: any(
                c["author"] == e["author"] and c["content"] == e["content"] for c in comments
            ),
        )
        comment_echoes[task["id"]] = pending_comments

        with st.expander(f"💬 הערות ({len(comments) + len(pending_comments)})"):
            # dir="rtl" keeps the avatar emoji on the right even when the
            # author's name is Latin (which would otherwise flip the line LTR).
            for comment in comments:
                avatar = AVATARS.get(comment["author"], DEFAULT_AVATAR)
                st.markdown(
                    f'<span dir="rtl">{avatar} '
                    f"<strong>{html.escape(comment['author'] or '')}</strong> · "
                    f"<small>{fmt_ts(comment['created_at'])}</small></span>",
                    unsafe_allow_html=True,
                )
                st.markdown(comment["content"])
                st.markdown("---")
            for echo in pending_comments:
                avatar = AVATARS.get(echo["author"], DEFAULT_AVATAR)
                st.markdown(
                    f'<span dir="rtl">{avatar} '
                    f"<strong>{html.escape(echo['author'])}</strong> · "
                    "<small>🕓 נשלח…</small></span>",
                    unsafe_allow_html=True,
                )
                st.markdown(echo["content"])
                st.markdown("---")

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

            # Deleting stays synchronous on purpose: destructive actions should
            # confirm against the DB before the row disappears from the UI.
            if st.button("🗑️ מחיקת המשימה", key=f"task_delete_{task['id']}"):
                db.delete_task(task["id"])
                st.rerun()


def _render_pending_task(echo: dict):
    # No interactive controls yet — the row has no database id until it syncs.
    status_col, body_col = st.columns([0.22, 0.78], vertical_alignment="center")
    status_col.markdown("🕓")
    with body_col:
        st.markdown(
            _task_title_html(
                echo["title"], echo["assignee"], is_done=False,
                is_urgent=echo.get("is_urgent", False),
            ),
            unsafe_allow_html=True,
        )
        st.caption("מסתנכרן עם מסד הנתונים…")


# Reconciliation (surviving_echoes / _effective_done / _effective_urgent
# below) only re-evaluates when this fragment executes. Without a poll, a
# background write that resolves while the user isn't clicking anything else
# in this board would sit at "מסתנכרן…" until some unrelated interaction
# happened to rerun it. The check itself is nearly free when nothing is
# pending — get_tasks()/get_comments_map() are cache hits for 30s
# (VOLATILE_TTL) at a time, so most of these ticks touch no database at all.
TASK_BOARD_POLL = "1s"


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
    # add_task/set_task_done/set_task_urgent/add_comment run on a background
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

    # --- Add a task --------------------------------------------------------
    with st.form(f"add_task_form_{scope}", clear_on_submit=True, border=False):
        title_col, assignee_col, urgent_col, button_col = st.columns(
            [0.47, 0.21, 0.14, 0.18], vertical_alignment="center"
        )
        title = title_col.text_input(
            "משימה", placeholder="משימה חדשה...", label_visibility="collapsed",
            key=f"task_title_{scope}",
        )
        assignee = assignee_col.selectbox(
            "אחראי/ת", db.get_users(), label_visibility="collapsed",
            key=f"task_assignee_{scope}",
        )
        is_urgent = urgent_col.checkbox(
            "🔥 דחוף", key=f"task_urgent_{scope}", help="סימון המשימה כדחופה"
        )
        if button_col.form_submit_button("➕ הוספה", use_container_width=True):
            text = title.strip()
            if text:
                future = optimistic.submit_write(
                    f"משימה '{text}'", db.add_task, text, assignee, user,
                    project_id, task_type, is_urgent,
                )
                st.session_state.setdefault(echo_key, []).append(
                    {
                        "title": text, "assignee": assignee, "created_by": user,
                        "is_urgent": is_urgent, "future": future,
                    }
                )
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

    open_count = len([t for t in tasks if not t["is_done"]]) + len(pending_tasks)
    total_count = len(tasks) + len(pending_tasks)
    st.caption(f'{open_count} פתוחות · {total_count} סה"כ')
    comments_map = db.get_comments_map(project_id=project_id, task_type=task_type)
    for task in tasks:
        _render_task(task, comments_map.get(task["id"], []))
    for echo in pending_tasks:
        _render_pending_task(echo)


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
    """Seam for the unread-badge feature (F3).

    F3 will upsert chat_reads.last_read_at here, debounced so it writes only
    when the project actually had unread messages — never on every poll tick.
    Deliberately a no-op until then.
    """


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
    tab_labels = ["📋 אפיון המוצר", "✅ משימות פיתוח", "💬 תקשורת צוות"]
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

    # Each bubble is a full-size button styled as a floating card (see theme.py),
    # so a click navigates straight into the project dashboard.
    bubbles = [
        {
            "label": f"📂 **{p['name']}**\n\nנוצר על ידי {p['created_by']} · {fmt_ts(p['created_at'])}",
            "key": f"bubble_project_{p['id']}",
            "view": ("project", p["id"]),
        }
        for p in projects
    ] + [
        {
            "label": f"🕓 **{e['name']}**\n\nנשמר כרגע במסד הנתונים…",
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
                    if st.button(bubble["label"], key=bubble["key"], use_container_width=True):
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
    """Compact home-screen widget with every open urgent task across all projects."""
    urgent_tasks = db.get_urgent_open_tasks()
    if not urgent_tasks:
        return

    st.markdown(
        f'<div class="welcome-section-title">🔥 משימות דחופות ({len(urgent_tasks)})</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="urgent_widget"):
        for task in urgent_tasks:
            source = task["project_name"] or (
                "משימות דחופות" if task["task_type"] == "urgent" else "רעיונות לעתיד"
            )
            assignee = f" · 👤 {task['assignee']}" if task["assignee"] else ""
            label = f"🔥 **{task['title']}**\n\n📂 {source}{assignee}"
            if st.button(label, key=f"urgent_widget_{task['id']}", use_container_width=True):
                if task["project_id"] is not None:
                    st.session_state["view"] = ("project", task["project_id"])
                else:
                    st.session_state["view"] = task["task_type"]
                st.rerun()
