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

import auth
import database as db
import optimistic

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


def go_home() -> None:
    """Clear the selected project and return to the main (bubbles) screen."""
    st.session_state["view"] = None


def render_sidebar():
    """Render navigation. Returns the current view: ('project', id) | ('pending_project', temp_id) | 'urgent' | 'backlog' | 'users' | None."""
    user = st.session_state["user"]

    with st.sidebar:
        st.markdown("## 🚀 צוות AI וחדשנות")
        st.caption(f"מחובר/ת: **{user}** {AVATARS.get(user, DEFAULT_AVATAR)}")

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

        top_left, top_right = st.columns(2)
        if top_left.button("🔄 רענון", use_container_width=True):
            st.cache_data.clear()  # force-pull teammates' latest changes
            st.rerun()
        if top_right.button("🚪 יציאה", use_container_width=True):
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


def _toggle_task(task_id: int, widget_key: str):
    """Optimistic toggle: remember the new status locally, sync in the background."""
    new_value = bool(st.session_state[widget_key])
    future = optimistic.submit_write(
        "סטטוס משימה", db.set_task_done, task_id, new_value, st.session_state["user"]
    )
    st.session_state.setdefault("task_done_override", {})[task_id] = {
        "value": new_value,
        "future": future,
    }


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


def _task_title_html(
    title: str, assignee: str | None, is_done: bool, is_urgent: bool = False
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
    # When completed, dim the whole line (tag and assignee included).
    return f'<span class="task-done">{body}</span>' if is_done else body


def _render_task(task: dict, comments: list[dict]):
    user = st.session_state["user"]
    done_key = f"task_done_{task['id']}"
    is_done, syncing = _effective_done(task)

    # If another user changed the task in the DB, let the DB value win.
    if done_key in st.session_state and bool(st.session_state[done_key]) != is_done:
        del st.session_state[done_key]

    check_col, body_col = st.columns([0.06, 0.94])
    with check_col:
        st.checkbox(
            "בוצע",
            value=is_done,
            key=done_key,
            label_visibility="collapsed",
            on_change=_toggle_task,
            args=(task["id"], done_key),
            help="סימון המשימה כבוצעה",
        )
    with body_col:
        st.markdown(
            _task_title_html(
                task["title"], task["assignee"], is_done, task.get("is_urgent", False)
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
            for comment in comments:
                avatar = AVATARS.get(comment["author"], DEFAULT_AVATAR)
                st.markdown(
                    f"{avatar} **{comment['author']}** · "
                    f"<small>{fmt_ts(comment['created_at'])}</small>",
                    unsafe_allow_html=True,
                )
                st.markdown(comment["content"])
                st.markdown("---")
            for echo in pending_comments:
                avatar = AVATARS.get(echo["author"], DEFAULT_AVATAR)
                st.markdown(
                    f"{avatar} **{echo['author']}** · <small>🕓 נשלח…</small>",
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
                        st.rerun()

            # Deleting stays synchronous on purpose: destructive actions should
            # confirm against the DB before the row disappears from the UI.
            if st.button("🗑️ מחיקת המשימה", key=f"task_delete_{task['id']}"):
                db.delete_task(task["id"])
                st.rerun()


def _render_pending_task(echo: dict):
    check_col, body_col = st.columns([0.06, 0.94])
    check_col.markdown("🕓")
    with body_col:
        st.markdown(
            _task_title_html(
                echo["title"], echo["assignee"], is_done=False,
                is_urgent=echo.get("is_urgent", False),
            ),
            unsafe_allow_html=True,
        )
        st.caption("מסתנכרן עם מסד הנתונים…")


def render_task_board(project_id: int | None = None, task_type: str = "project"):
    user = st.session_state["user"]
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
                st.rerun()

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
# Module C — Project chat
# ---------------------------------------------------------------------------


def _render_chat(project_id: int):
    user = st.session_state["user"]
    echo_key = f"optimistic_chat_{project_id}"

    messages = db.get_chat(project_id)
    pending = optimistic.surviving_echoes(
        st.session_state.get(echo_key, []),
        landed=lambda e: any(
            m["sender"] == e["sender"] and m["message"] == e["message"] for m in messages
        ),
    )
    st.session_state[echo_key] = pending

    for msg in messages:
        avatar = AVATARS.get(msg["sender"], DEFAULT_AVATAR)
        with st.chat_message(msg["sender"] or "unknown", avatar=avatar):
            st.markdown(f"**{msg['sender']}** · `{fmt_ts(msg['created_at'])}`")
            st.markdown(msg["message"])
    for echo in pending:
        avatar = AVATARS.get(echo["sender"], DEFAULT_AVATAR)
        with st.chat_message(echo["sender"], avatar=avatar):
            st.markdown(f"**{echo['sender']}** · 🕓 *נשלח…*")
            st.markdown(echo["message"])

    prompt = st.chat_input("כתבו הודעה לצוות...", key=f"chat_input_{project_id}")
    if prompt and prompt.strip():
        text = prompt.strip()
        future = optimistic.submit_write(
            "הודעה בצ'אט", db.add_chat_message, project_id, text, user
        )
        st.session_state.setdefault(echo_key, []).append(
            {"sender": user, "message": text, "future": future}
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def render_project_dashboard(project: dict):
    st.title(f"📂 {project['name']}")
    st.caption(f"נוצר על ידי {project['created_by']} · {fmt_ts(project['created_at'])}")

    spec_tab, tasks_tab, chat_tab = st.tabs(
        ["📋 אפיון המוצר", "✅ משימות פיתוח", "💬 תקשורת צוות"]
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


def render_welcome():
    """Personalized greeting + floating project bubbles (main screen)."""
    user = st.session_state["user"]

    st.markdown(
        f'<div class="welcome-greeting">ברוך הבא, {html.escape(user)} 👋</div>'
        '<div class="welcome-sub">צוות AI וחדשנות · דשבורד ניהול משימות</div>',
        unsafe_allow_html=True,
    )

    projects = db.get_projects()
    pending_projects = st.session_state.get("optimistic_projects", [])

    if not projects and not pending_projects:
        st.info("עדיין אין פרויקטים — הוסיפו פרויקט חדש מהסרגל הימני.")
        return

    st.markdown('<div class="welcome-section-title">הפרויקטים שלנו</div>', unsafe_allow_html=True)

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
