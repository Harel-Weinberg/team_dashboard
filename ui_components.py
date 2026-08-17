"""
ui_components.py — All reusable UI pieces:

* render_sidebar()            — navigation, Projects Hub, Add New Project
* render_project_dashboard()  — Spec / Tasks / Chat tabs for one project
* render_task_board()         — reusable task list (also powers Urgent & Backlog)
* render_adhoc_board()        — Urgent Tasks / Future Backlog pages
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

import auth
import database as db

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


def render_sidebar():
    """Render navigation. Returns the current view: ('project', id) | 'urgent' | 'backlog' | None."""
    user = st.session_state["user"]

    with st.sidebar:
        st.markdown("## 🚀 AI & Tech Innovation")
        st.caption(f"Signed in as **{user}** {AVATARS.get(user, DEFAULT_AVATAR)}")

        top_left, top_right = st.columns(2)
        if top_left.button("🔄 Refresh", use_container_width=True):
            st.rerun()
        if top_right.button("🚪 Log out", use_container_width=True):
            auth.logout()

        st.divider()

        # --- Projects Hub -------------------------------------------------
        st.markdown("### 📁 Projects Hub")
        projects = db.get_projects()
        if not projects:
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

        # --- Add New Project ----------------------------------------------
        with st.form("add_project_form", clear_on_submit=True, border=False):
            new_name = st.text_input(
                "New project",
                placeholder="New project name...",
                label_visibility="collapsed",
            )
            if st.form_submit_button("➕ Add New Project", use_container_width=True):
                name = new_name.strip()
                if not name:
                    st.warning("Please enter a project name.")
                else:
                    new_id = db.add_project(name, user)
                    if new_id is None:
                        st.warning(f"A project named '{name}' already exists.")
                    else:
                        st.session_state["view"] = ("project", new_id)
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
    db.set_task_done(task_id, st.session_state[widget_key], st.session_state["user"])


def _render_task(task: dict):
    user = st.session_state["user"]
    done_key = f"task_done_{task['id']}"

    # If another user changed the task in the DB, let the DB value win.
    if done_key in st.session_state and bool(st.session_state[done_key]) != bool(task["is_done"]):
        del st.session_state[done_key]

    check_col, body_col = st.columns([0.06, 0.94])
    with check_col:
        st.checkbox(
            "Done",
            value=bool(task["is_done"]),
            key=done_key,
            label_visibility="collapsed",
            on_change=_toggle_task,
            args=(task["id"], done_key),
        )
    with body_col:
        title = f"~~{task['title']}~~" if task["is_done"] else f"**{task['title']}**"
        assignee = f" · 👤 `{task['assignee']}`" if task["assignee"] else ""
        st.markdown(title + assignee)

        meta = f"Created by {task['created_by']} · {fmt_ts(task['created_at'])}"
        if task["is_done"] and task["completed_by"]:
            meta += f" · ✅ Completed by {task['completed_by']} at {fmt_ts(task['completed_at'])}"
        st.caption(meta)

        comments = db.get_comments(task["id"])
        with st.expander(f"💬 Notes ({len(comments)})"):
            for comment in comments:
                avatar = AVATARS.get(comment["author"], DEFAULT_AVATAR)
                st.markdown(
                    f"{avatar} **{comment['author']}** · "
                    f"<small>{fmt_ts(comment['created_at'])}</small>",
                    unsafe_allow_html=True,
                )
                st.markdown(comment["content"])
                st.markdown("---")

            with st.form(f"comment_form_{task['id']}", clear_on_submit=True, border=False):
                note = st.text_area(
                    "Leave a note on this task",
                    height=80,
                    placeholder="Write a note about this specific task...",
                )
                if st.form_submit_button("Add note"):
                    if note.strip():
                        db.add_comment(task["id"], note.strip(), user)
                        st.rerun()

            if st.button("🗑️ Delete task", key=f"task_delete_{task['id']}"):
                db.delete_task(task["id"])
                st.rerun()


def render_task_board(project_id: int | None = None, task_type: str = "project"):
    user = st.session_state["user"]
    scope = f"{task_type}_{project_id if project_id is not None else 'global'}"

    # --- Add new task ------------------------------------------------------
    with st.form(f"add_task_form_{scope}", clear_on_submit=True, border=False):
        title_col, assignee_col, button_col = st.columns([0.58, 0.24, 0.18])
        title = title_col.text_input(
            "Task", placeholder="New task...", label_visibility="collapsed"
        )
        assignee = assignee_col.selectbox(
            "Assign to", db.get_users(), label_visibility="collapsed"
        )
        if button_col.form_submit_button("➕ Add", use_container_width=True):
            if title.strip():
                db.add_task(title.strip(), assignee, user, project_id, task_type)
                st.rerun()

    # --- Task list -----------------------------------------------------------
    tasks = db.get_tasks(project_id=project_id, task_type=task_type)
    if not tasks:
        st.info("No tasks yet. Add the first one above.")
        return

    open_tasks = [t for t in tasks if not t["is_done"]]
    st.caption(f"{len(open_tasks)} open / {len(tasks)} total")
    for task in tasks:
        _render_task(task)


# ---------------------------------------------------------------------------
# Module C — Project chat
# ---------------------------------------------------------------------------


def _render_chat(project_id: int):
    user = st.session_state["user"]

    for msg in db.get_chat(project_id):
        avatar = AVATARS.get(msg["sender"], DEFAULT_AVATAR)
        with st.chat_message(msg["sender"] or "unknown", avatar=avatar):
            st.markdown(f"**{msg['sender']}** · `{fmt_ts(msg['created_at'])}`")
            st.markdown(msg["message"])

    prompt = st.chat_input("Message the team...", key=f"chat_input_{project_id}")
    if prompt:
        db.add_chat_message(project_id, prompt.strip(), user)
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
