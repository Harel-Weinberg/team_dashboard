"""Verify the "change username" feature against the real Supabase database.

Run with:  python test_rename_user.py

Covers:
  1. Validation rules (empty, too short, bad characters, duplicate, unchanged).
  2. Atomic rename + re-attribution of every identity column
     (projects, specs, tasks x3, task_comments, project_chat).
  3. Login works with the new name and fails with the old one.
  4. Renaming yourself through the real UI updates st.session_state["user"],
     so subsequent actions are tagged with the new name.
  5. Nothing is left behind (cleanup).
"""

import admin_ui
import auth
import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, create_temp_admin, login, new_app

RENAMED = "temp_test_admin_renamed"
TEMP_PROJECT = "temp_test_rename_project"


def _cleanup():
    for name in (TEMP_PROJECT,):
        with db.get_cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE name = %s", (name,))
            row = cur.fetchone()
        if row:
            db.delete_project(row["id"])
    for user in (TEMP_ADMIN, RENAMED):
        db.delete_user(user)


def _seed_activity(username: str) -> int:
    """Create one row in every identity-tagged table, authored by `username`."""
    project_id = db.add_project(TEMP_PROJECT, username)
    db.save_spec(project_id, "spec content", username)
    db.add_task("rename test task", username, username, project_id, "project")
    task = next(t for t in db.get_tasks(project_id=project_id) if t["title"] == "rename test task")
    db.set_task_done(task["id"], True, username)  # sets completed_by
    db.add_comment(task["id"], "rename test note", username)
    db.add_chat_message(project_id, "rename test message", username)
    db.mark_scope_read(username, db.SCOPE_PROJECT_CHAT, project_id)  # read_receipts row
    return project_id


def _attribution_counts(username: str) -> dict[str, int]:
    counts = {}
    with db.get_cursor() as cur:
        for table, column in db._IDENTITY_COLUMNS:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s", (username,)
            )
            counts[f"{table}.{column}"] = cur.fetchone()["n"]
    return counts


def test_validation():
    cases = [
        ("", "נא להזין"),                          # empty
        ("a", "תווים"),                            # too short
        ("has space", "רווחים"),                   # invalid character
        ("bad/slash", "רווחים"),                   # invalid character
        ("x" * 33, "תווים"),                       # too long
        (TEMP_ADMIN, "שם המשתמש הנוכחי"),          # unchanged
        ("Harel", "כבר קיים"),                     # duplicate (real user)
        ("harel", "כבר קיים"),                     # duplicate, case-insensitive
    ]
    for candidate, expected in cases:
        error = admin_ui._validate_username(candidate, current_name=TEMP_ADMIN)
        assert error and expected in error, f"{candidate!r} -> {error!r} (expected {expected!r})"
    assert admin_ui._validate_username(RENAMED, current_name=TEMP_ADMIN) is None
    assert admin_ui._validate_username("שם_בעברית", current_name=TEMP_ADMIN) is None
    print(f"PASS: validation rejects {len(cases)} bad names, accepts Latin + Hebrew names")


def test_rename_reattributes_everything():
    project_id = _seed_activity(TEMP_ADMIN)
    before = _attribution_counts(TEMP_ADMIN)
    assert all(n > 0 for n in before.values()), f"Seeding incomplete: {before}"

    reattributed = db.rename_user(TEMP_ADMIN, RENAMED)
    assert reattributed is not None, "Rename failed"
    assert reattributed == sum(before.values()), (
        f"Reported {reattributed}, expected {sum(before.values())}"
    )

    assert db.get_user(TEMP_ADMIN) is None, "Old username should no longer exist"
    new_row = db.get_user(RENAMED)
    assert new_row is not None and new_row["role"] == "admin", "Role must be preserved"

    stale = _attribution_counts(TEMP_ADMIN)
    assert sum(stale.values()) == 0, f"Old name still attributed somewhere: {stale}"
    after = _attribution_counts(RENAMED)
    assert after == before, f"Attribution mismatch: {before} -> {after}"
    print(f"PASS: rename re-attributed {reattributed} rows across "
          f"{len(before)} identity columns, role preserved")
    return project_id


def test_login_with_new_name():
    assert auth._verify(RENAMED, TEMP_ADMIN_PW), "Password must still work after rename"
    assert not auth._verify(TEMP_ADMIN, TEMP_ADMIN_PW), "Old username must no longer authenticate"
    at = login(new_app(), RENAMED, TEMP_ADMIN_PW)
    assert at.session_state["user"] == RENAMED, "Login with new username failed"
    print("PASS: login works with the new username, old username rejected")


def test_duplicate_rename_is_rejected():
    assert db.rename_user(RENAMED, "Harel") is None, "Renaming onto an existing user must fail"
    assert db.get_user(RENAMED) is not None, "Failed rename must leave the user intact"
    real = db.get_user("Harel")
    assert real is not None and real["role"] == "admin", "Real user must be untouched"
    print("PASS: rename onto an existing username is rejected atomically")


def test_ui_rename_updates_session_state():
    """Rename yourself through the real UI and confirm the session follows."""
    at = login(new_app(), RENAMED, TEMP_ADMIN_PW)
    at.session_state["view"] = "users"
    at = at.run()
    assert not at.exception, f"User Management crashed: {at.exception[0]}"

    at.selectbox(key="rename_target").select(RENAMED)
    at.text_input(key="rename_new_name").set_value(TEMP_ADMIN)
    submit = next(b for b in at.button if b.key and "rename_user_form" in b.key)
    at = submit.set_value(True).run()

    assert not at.exception, f"Rename crashed: {at.exception[0]}"
    assert at.session_state["user"] == TEMP_ADMIN, (
        f"session_state['user'] not updated: {at.session_state['user']!r}"
    )
    assert at.session_state["role"] == "admin", "Role must survive the rename"
    assert db.get_user(TEMP_ADMIN) is not None and db.get_user(RENAMED) is None
    assert any("שם המשתמש שונה" in (s.value or "") for s in at.success), (
        f"Expected a success message, got {[s.value for s in at.success]}"
    )
    print("PASS: UI rename of the active user updates session_state and shows confirmation")

    # A write made after the rename must be tagged with the NEW name.
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        project_id = cur.fetchone()["id"]
    db.add_chat_message(project_id, "post-rename message", at.session_state["user"])
    senders = {m["sender"] for m in db.get_chat(project_id)}
    assert TEMP_ADMIN in senders and RENAMED not in senders, f"Bad attribution: {senders}"
    print("PASS: actions after the rename are tagged with the new username")


if __name__ == "__main__":
    _cleanup()
    create_temp_admin()
    try:
        test_validation()
        test_rename_reattributes_everything()
        test_login_with_new_name()
        test_duplicate_rename_is_rejected()
        test_ui_rename_updates_session_state()
    finally:
        _cleanup()
    print("\nALL RENAME TESTS PASSED")
