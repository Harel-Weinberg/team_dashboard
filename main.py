"""
main.py — Entry point for the AI & Tech Innovation Team Dashboard.

Run with:  streamlit run main.py
"""

import streamlit as st

import admin_ui
import auth
import database as db
import optimistic
import ui_components as ui

st.set_page_config(
    page_title="AI & Tech Innovation — Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main():
    # 1. Ensure schema exists and default admins are seeded (cached — runs
    #    once per server process). Must run before login: auth reads the
    #    users table.
    try:
        db.init_db()
    except Exception as exc:  # noqa: BLE001 — surface any startup/DB failure cleanly
        st.error(f"Cannot reach the database — check .streamlit/secrets.toml.\n\n{exc}")
        st.stop()

    # 2. Authentication gate.
    if not auth.require_login():
        st.stop()

    # 3. Surface any failed background (optimistic) writes from earlier actions.
    optimistic.report_sync_failures()

    # 4. Navigation + routing.
    view = ui.render_sidebar()

    if view == "urgent":
        ui.render_adhoc_board(
            "🔥 Urgent Tasks",
            "Ad-hoc critical bugs and urgent daily tasks (not tied to a project).",
            task_type="urgent",
        )
    elif view == "backlog":
        ui.render_adhoc_board(
            "💡 Future Backlog",
            "Future ideas and long-term features.",
            task_type="backlog",
        )
    elif view == "users":
        admin_ui.render_user_management()
    elif isinstance(view, tuple) and view[0] == "pending_project":
        ui.render_pending_project(view[1])
    elif isinstance(view, tuple) and view[0] == "project":
        project = db.get_project(view[1])
        if project is None:
            st.session_state.pop("view", None)
            st.warning("This project no longer exists.")
        else:
            ui.render_project_dashboard(project)
    else:
        ui.render_welcome()


if __name__ == "__main__":
    main()
