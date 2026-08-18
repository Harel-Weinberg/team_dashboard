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
import perf
import theme
import ui_components as ui

st.set_page_config(
    page_title="צוות AI וחדשנות — דשבורד",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _view_key(view) -> str:
    """A stable, DOM-safe identifier for the current view."""
    if isinstance(view, tuple):
        return f"{view[0]}_{view[1]}"
    return str(view or "home")


@perf.track("main")
def main():
    # 1. Ensure schema exists and default admins are seeded (cached — runs
    #    once per server process). Must run before login: auth reads the
    #    users table.
    try:
        # Resolve the connection pool on the render thread. Background workers
        # then borrow from a plain module global and never touch st.secrets or
        # st.cache_resource themselves (see database.py thread discipline).
        db.ensure_pool()
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

    # 4. Apply cache invalidations queued by background writes, then surface any
    #    failed background (optimistic) writes from earlier actions,
    #    plus any toast queued by an action that triggered a rerun.
    db.drain_deferred_invalidations()
    optimistic.report_sync_failures()
    if toast := st.session_state.pop("pending_toast", None):
        st.toast(toast)

    # 4. Navigation + routing.
    view = ui.render_sidebar()

    # Each view renders inside a container keyed by that view's identity.
    #
    # Without this, consecutive views occupy the same position in the element
    # tree and Streamlit's client morphs one into the other rather than
    # swapping them, so for a frame you see the previous screen's widgets under
    # the new screen's heading — e.g. the empty-task-board message flashing on
    # the user-management page. Distinct keys make them distinct subtrees.
    with st.container(key=f"view_{_view_key(view)}"):
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
