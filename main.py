"""
main.py — Entry point for the AI & Tech Innovation Team Dashboard.

Run with:  streamlit run main.py
"""

import streamlit as st

import admin_ui
import auth
import database as db
import notifications
import optimistic
import theme
import ui_components as ui

st.set_page_config(
    page_title="צוות AI וחדשנות — דשבורד",
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
        st.error(f"אין חיבור למסד הנתונים — בדקו את .streamlit/secrets.toml.\n\n{exc}")
        st.stop()

    # Publish notification settings to os.environ on the main thread, so the
    # background sender threads only read environment variables.
    notifications.bootstrap_from_secrets()

    # 2. Authentication gate.
    if not auth.require_login():
        st.stop()

    # 3. Global RTL (Hebrew) layout + component styling.
    theme.inject_app_css()

    # 4. Surface any failed background (optimistic) writes from earlier actions,
    #    plus any toast queued by an action that triggered a rerun.
    optimistic.report_sync_failures()
    if toast := st.session_state.pop("pending_toast", None):
        st.toast(toast)

    # 4. Navigation + routing.
    view = ui.render_sidebar()

    if view == "urgent":
        ui.render_adhoc_board(
            "🔥 משימות דחופות",
            "באגים קריטיים ומשימות יומיות דחופות שאינן משויכות לפרויקט מסוים.",
            task_type="urgent",
        )
    elif view == "backlog":
        ui.render_adhoc_board(
            "💡 רעיונות לעתיד",
            "רעיונות ופיצ'רים לטווח הארוך.",
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
            st.warning("הפרויקט הזה אינו קיים יותר.")
        else:
            ui.render_project_dashboard(project)
    else:
        ui.render_welcome()


if __name__ == "__main__":
    main()
