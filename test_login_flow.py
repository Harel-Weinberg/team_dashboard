"""Verify DB-driven auth + user management against the real Supabase database.

Run with:  python test_login_flow.py

Covers:
  1. Login screen renders with users fetched from the DB (default admins seeded).
  2. Wrong password rejected.
  3. Correct password logs in, role stored, admin sees User Management nav.
  4. User Management page renders for an admin.
  5. DB-level round-trip: add user -> verify login -> change password -> delete.
"""

from streamlit.testing.v1 import AppTest

DUMMY_PASSWORDS = {"Harel": "harel2026", "Yitzhak": "yitzhak2026"}
TEMP_USER = "temp_test_user_delete_me"


def new_app() -> AppTest:
    at = AppTest.from_file("main.py", default_timeout=60)
    return at.run()


def current_user(at: AppTest):
    return at.session_state["user"] if "user" in at.session_state else None


def login(at: AppTest, username: str, password: str) -> AppTest:
    at.selectbox[0].select(username)
    at.text_input[0].set_value(password)
    return at.button[0].set_value(True).run()


def test_login_screen_renders():
    at = new_app()
    assert not at.exception, f"App crashed on load: {at.exception[0] if at.exception else ''}"
    users = at.selectbox[0].options
    assert "Harel" in users and "Yitzhak" in users, f"Default admins not seeded: {users}"
    print("PASS: login screen renders, DB-seeded users:", users)


def test_wrong_password_rejected():
    at = login(new_app(), "Harel", "wrong-password")
    assert not current_user(at), "User must NOT be logged in"
    assert at.error and "Incorrect password" in at.error[0].value
    print("PASS: wrong password rejected")


def test_admin_login_and_nav(username: str):
    at = login(new_app(), username, DUMMY_PASSWORDS[username])
    assert not at.exception, f"App crashed after login: {at.exception[0]}"
    assert current_user(at) == username
    assert at.session_state["role"] == "admin", f"Expected admin role, got {at.session_state['role']}"
    nav_keys = [b.key for b in at.button]
    assert "nav_users" in nav_keys, f"Admin should see User Management nav, got {nav_keys}"
    print(f"PASS: {username} logged in as admin, User Management nav visible")
    return at


def test_user_management_page():
    at = test_admin_login_and_nav("Harel")
    at.session_state["view"] = "users"
    at.run()
    assert not at.exception, f"User Management page crashed: {at.exception[0]}"
    assert at.dataframe, "Expected the users table on the User Management page"
    print("PASS: User Management page renders with users table")


def test_db_user_crud():
    import auth
    import database as db

    db.delete_user(TEMP_USER)  # clean slate if a previous run aborted
    assert db.add_user(TEMP_USER, auth.hash_password("secret123"), "user")
    assert not db.add_user(TEMP_USER, auth.hash_password("x" * 8)), "Duplicate must be rejected"
    assert auth._verify(TEMP_USER, "secret123"), "New user should authenticate"

    db.set_user_password(TEMP_USER, auth.hash_password("newpass456"))
    assert not auth._verify(TEMP_USER, "secret123"), "Old password must stop working"
    assert auth._verify(TEMP_USER, "newpass456"), "New password should authenticate"

    db.delete_user(TEMP_USER)
    assert db.get_user(TEMP_USER) is None, "User should be gone after delete"
    assert db.count_admins() >= 1
    print("PASS: DB-level add / duplicate-reject / verify / change password / delete")


if __name__ == "__main__":
    test_login_screen_renders()
    test_wrong_password_rejected()
    test_admin_login_and_nav("Harel")
    test_admin_login_and_nav("Yitzhak")
    test_user_management_page()
    test_db_user_crud()
    print("\nALL TESTS PASSED")
