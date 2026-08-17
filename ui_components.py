"""
ui_components.py — All reusable UI pieces:

* render_sidebar()            — navigation, Projects Hub, Add New Project
* render_project_dashboard()  — Spec / Tasks / Chat tabs for one project
* render_task_board()         — reusable task list (also powers Urgent & Backlog)
* render_adhoc_board()        — Urgent Tasks / Future Backlog pages
* render_pending_project()    — placeholder while a new project syncs to the DB

Write operations follow the Optimistic UI pattern (see optimistic.py): the
change appears instantly from st.session_state while the database write runs
on a background thread; failed syncs surface as warnings and the UI falls
back to database truth.
"""

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
            st.warning(f"A project named '{entry['name']}' already exists.")
            if selected_here:
                st.session_state["view"] = None
        elif selected_here:
            st.session_state["view"] = ("project", new_id)
    st.session_state["optimistic_projects"] = pending
    return pending


def render_sidebar():
    """Render navigation. Returns the current view: ('project', id) | ('pending_project', temp_id) | 'urgent' | 'backlog' | 'users' | None."""
    user = st.session_state["user"]

    with st.sidebar:
        st.markdown("## 🚀 AI & Tech Innovation")
        st.caption(f"Signed in as **{user}** {AVATARS.get(user, DEFAULT_AVATAR)}")

        top_left, top_right = st.columns(2)
        if top_left.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()  # force-pull teammates' latest changes
            st.rerun()
        if top_right.button("🚪 Log out", use_container_width=True):
            auth.logout()

        st.divider()

        # --- Projects Hub -------------------------------------------------
        st.markdown("### 📁 Projects Hub")
        pending_projects = _resolve_pending_projects()
        projects = db.get_projects()
        if not projects and not pending_projects:
            st.caption("No projects yet — add one below.")
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

        # --- Add New Project ----------------------------------------------
        with st.form("add_project_form", clear_on_submit=True, border=False):
            new_name = st.text_input(
                "New project",
                placeholder="New project name...",
                label_visibility="collapsed",
                key="new_project_name",
            )
            if st.form_submit_button("➕ Add New Project", use_container_width=True):
                name = new_name.strip()
                if not name:
                    st.warning("Please enter a project name.")
                else:
                    temp_id = uuid.uuid4().hex
                    future = optimistic.submit_write(
                        f"new project '{name}'", db.add_project, name, user
                    )
                    st.session_state.setdefault("optimistic_projects", []).append(
                        {"temp_id": temp_id, "name": name, "future": future}
                    )
                    st.session_state["view"] = ("pending_project", temp_id)
                    st.rerun()

        st.divider()

        # --- Standalone pages ----------------------------------------------
        pages = [("🔥 Urgent Tasks", "urgent"), ("💡 Future Backlog", "backlog")]
        if auth.is_admin():
            pages.append(("👥 User Management", "users"))
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
# Module A — Product Specification
# ---------------------------------------------------------------------------


def _render_spec(project_id: int):
    user = st.session_state["user"]
    spec = db.get_spec(project_id)

    content = st.text_area(
        "Project characterization, logic and product spec — edited collaboratively:",
        value=spec["content"],
        height=420,
        key=f"spec_text_{project_id}",
        placeholder="Describe the product, its logic, flows, edge cases...",
    )
    if st.button("💾 Save Specification", type="primary", key=f"spec_save_{project_id}"):
        db.save_spec(project_id, content, user)
        st.rerun()

    if spec["updated_by"]:
        st.caption(f"*Last updated by **{spec['updated_by']}** at {fmt_ts(spec['updated_at'])}*")
    else:
        st.caption("*Not saved yet.*")


# ---------------------------------------------------------------------------
# Module B — Task board (shared by projects, Urgent and Backlog)
# ---------------------------------------------------------------------------


def _toggle_task(task_id: int, widget_key: str):
    """Optimistic toggle: remember the new status locally, sync in the background."""
    new_value = bool(st.session_state[widget_key])
    future = optimistic.submit_write(
        "task status update", db.set_task_done, task_id, new_value, st.session_state["user"]
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
            "Done",
            value=is_done,
            key=done_key,
            label_visibility="collapsed",
            on_change=_toggle_task,
            args=(task["id"], done_key),
        )
    with body_col:
        title = f"~~{task['title']}~~" if is_done else f"**{task['title']}**"
        assignee = f" · 👤 `{task['assignee']}`" if task["assignee"] else ""
        st.markdown(title + assignee)

        meta = f"Created by {task['created_by']} · {fmt_ts(task['created_at'])}"
        if syncing:
            meta += " · 🕓 syncing…"
        elif is_done and task["completed_by"]:
            meta += f" · ✅ Completed by {task['completed_by']} at {fmt_ts(task['completed_at'])}"
        st.caption(meta)

        comment_echoes = st.session_state.setdefault("optimistic_comments", {})
        pending_comments = optimistic.surviving_echoes(
            comment_echoes.get(task["id"], []),
            landed=lambda e: any(
                c["author"] == e["author"] and c["content"] == e["content"] for c in comments
            ),
        )
        comment_echoes[task["id"]] = pending_comments

        with st.expander(f"💬 Notes ({len(comments) + len(pending_comments)})"):
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
                    f"{avatar} **{echo['author']}** · <small>🕓 sending…</small>",
                    unsafe_allow_html=True,
                )
                st.markdown(echo["content"])
                st.markdown("---")

            with st.form(f"comment_form_{task['id']}", clear_on_submit=True, border=False):
                note = st.text_area(
                    "Leave a note on this task",
                    height=80,
                    placeholder="Write a note about this specific task...",
                    key=f"comment_text_{task['id']}",
                )
                if st.form_submit_button("Add note"):
                    text = note.strip()
                    if text:
                        future = optimistic.submit_write(
                            "task note", db.add_comment, task["id"], text, user
                        )
                        comment_echoes.setdefault(task["id"], []).append(
                            {"author": user, "content": text, "future": future}
                        )
                        st.rerun()

            # Deleting stays synchronous on purpose: destructive actions should
            # confirm against the DB before the row disappears from the UI.
            if st.button("🗑️ Delete task", key=f"task_delete_{task['id']}"):
                db.delete_task(task["id"])
                st.rerun()


def _render_pending_task(echo: dict):
    check_col, body_col = st.columns([0.06, 0.94])
    check_col.markdown("🕓")
    with body_col:
        assignee = f" · 👤 `{echo['assignee']}`" if echo["assignee"] else ""
        st.markdown(f"**{echo['title']}**" + assignee)
        st.caption("Syncing to the database…")


def render_task_board(project_id: int | None = None, task_type: str = "project"):
    user = st.session_state["user"]
    scope = f"{task_type}_{project_id if project_id is not None else 'global'}"
    echo_key = f"optimistic_tasks_{scope}"

    # --- Add new task ------------------------------------------------------
    with st.form(f"add_task_form_{scope}", clear_on_submit=True, border=False):
        title_col, assignee_col, button_col = st.columns([0.58, 0.24, 0.18])
        title = title_col.text_input(
            "Task", placeholder="New task...", label_visibility="collapsed",
            key=f"task_title_{scope}",
        )
        assignee = assignee_col.selectbox(
            "Assign to", db.get_users(), label_visibility="collapsed",
            key=f"task_assignee_{scope}",
        )
        if button_col.form_submit_button("➕ Add", use_container_width=True):
            text = title.strip()
            if text:
                future = optimistic.submit_write(
                    f"task '{text}'", db.add_task, text, assignee, user, project_id, task_type
                )
                st.session_state.setdefault(echo_key, []).append(
                    {"title": text, "assignee": assignee, "created_by": user, "future": future}
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
        st.info("No tasks yet. Add the first one above.")
        return

    open_tasks = [t for t in tasks if not t["is_done"]]
    st.caption(f"{len(open_tasks) + len(pending_tasks)} open / {len(tasks) + len(pending_tasks)} total")
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
            st.markdown(f"**{echo['sender']}** · 🕓 *sending…*")
            st.markdown(echo["message"])

    prompt = st.chat_input("Message the team...", key=f"chat_input_{project_id}")
    if prompt and prompt.strip():
        text = prompt.strip()
        future = optimistic.submit_write(
            "chat message", db.add_chat_message, project_id, text, user
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
    st.caption(f"Created by {project['created_by']} · {fmt_ts(project['created_at'])}")

    spec_tab, tasks_tab, chat_tab = st.tabs(
        ["📋 Product Specification", "✅ Development Tasks", "💬 Project Communication"]
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
        st.info(f"🕓 Creating project **{entry['name']}** — syncing to the database…")

    _poll()


def render_adhoc_board(title: str, subtitle: str, task_type: str):
    st.title(title)
    st.caption(subtitle)
    render_task_board(project_id=None, task_type=task_type)


def render_welcome():
    st.title("🚀 AI & Tech Innovation — Team Dashboard")
    st.markdown(
        """
        Welcome! Use the sidebar to get started:

        - **📁 Projects Hub** — open a project to see its spec, tasks and chat.
        - **➕ Add New Project** — create a new project (e.g. *AI Bot*, *Document Converter*).
        - **🔥 Urgent Tasks** — ad-hoc critical bugs and daily urgent items.
        - **💡 Future Backlog** — ideas and long-term features.

        Every change is tagged with your name and a timestamp, and syncs
        instantly to the cloud database — click **🔄 Refresh** to pull your
        teammate's latest updates.
        """
    )
