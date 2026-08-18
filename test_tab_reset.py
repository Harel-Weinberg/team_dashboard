"""Verify the project dashboard always opens on the spec tab.

Run with:  python test_tab_reset.py

st.tabs has no session_state-visible "active tab" (AppTest can't read that —
it's frontend-only), so this can't be checked by asserting on session_state.
What CAN be checked, and is what actually controls whether the browser keeps
the previously-clicked tab across a project switch, is the tabs widget's own
identity: st.tabs(..., key=f"project_tabs_{project_id}") must produce a
DIFFERENT underlying element id per project, or the frontend treats it as the
same widget and keeps whatever tab was last active.
"""

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_A = "temp_test_tab_reset_a"
TEMP_B = "temp_test_tab_reset_b"


def _cleanup_projects():
    for name in (TEMP_A, TEMP_B):
        with db.get_cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE name = %s", (name,))
            row = cur.fetchone()
        if row:
            db.delete_project(row["id"])


def _find_tab_container_blocks(node, out):
    if getattr(node, "type", None) == "tab_container":
        out.append(node)
    for child in (getattr(node, "children", None) or {}).values():
        _find_tab_container_blocks(child, out)


def _tab_container_block(at):
    found = []
    _find_tab_container_blocks(at.main, found)
    assert len(found) == 1, f"expected exactly 1 tabs widget on the project page, found {len(found)}"
    return found[0]


def test_each_project_gets_its_own_tabs_widget(pid_a, pid_b):
    """Different project_id -> different tabs widget id -> the frontend can't
    carry over a previously-selected tab, because it's not the same widget."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)

    at.session_state["view"] = ("project", pid_a)
    at = at.run()
    block_a = _tab_container_block(at)
    assert not at.exception, at.exception[0] if at.exception else None

    at.session_state["view"] = ("project", pid_b)
    at = at.run()
    block_b = _tab_container_block(at)
    assert not at.exception, at.exception[0] if at.exception else None

    assert block_a.proto.id != block_b.proto.id, (
        "both projects render the SAME tabs widget id — switching projects "
        "would not remount st.tabs, so the browser would keep whichever tab "
        "was last clicked instead of resetting to the spec tab"
    )
    assert f"project_tabs_{pid_a}" in block_a.proto.id
    assert f"project_tabs_{pid_b}" in block_b.proto.id
    print("PASS: each project's tabs render as a distinct widget "
          f"({block_a.proto.id.rsplit('-', 1)[-1]} vs {block_b.proto.id.rsplit('-', 1)[-1]})")


def test_spec_is_the_first_rendered_tab(pid_a):
    """The spec tab must be first in document order, since default= points at
    labels[0] — if a label gets reordered later, this must fail loudly."""
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    at.session_state["view"] = ("project", pid_a)
    at = at.run()
    assert not at.exception, at.exception[0] if at.exception else None
    assert len(at.tabs) == 3, f"expected 3 tabs on the project page, found {len(at.tabs)}"
    assert at.tabs[0].label == "📋 אפיון המוצר", (
        f"spec must be the first tab (index 0, the configured default); "
        f"got {[t.label for t in at.tabs]}"
    )
    print("PASS: spec renders as the first tab")


if __name__ == "__main__":
    create_temp_admin()
    _cleanup_projects()
    pid_a = db.add_project(TEMP_A, TEMP_ADMIN)
    pid_b = db.add_project(TEMP_B, TEMP_ADMIN)
    try:
        test_each_project_gets_its_own_tabs_widget(pid_a, pid_b)
        test_spec_is_the_first_rendered_tab(pid_a)
        print("\nALL TAB-RESET TESTS PASSED")
    finally:
        _cleanup_projects()
        cleanup()
