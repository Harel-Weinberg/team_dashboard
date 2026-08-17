"""
database.py — All data access for the Team Dashboard.

Connects to a cloud PostgreSQL database (Supabase) using credentials from
st.secrets. A fresh connection is opened per transaction and closed right
after: Supabase's connection pooler (port 6543, transaction mode) does the
actual pooling server-side, which keeps this safe when the app runs
concurrently from multiple computers.
"""

import hashlib
from contextlib import contextmanager

import psycopg2
import psycopg2.errors
import streamlit as st
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


def _connect():
    cfg = st.secrets["database"]
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        sslmode="require",
        connect_timeout=10,
    )


@contextmanager
def get_cursor():
    """Yield a dict-cursor inside a transaction; commit on success, rollback on error."""
    conn = _connect()
    try:
        with conn:  # transaction scope: commit/rollback
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT,
    role           TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_by  TEXT REFERENCES users(username),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS specs (
    project_id  INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT NOT NULL DEFAULT '',
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
    id            SERIAL PRIMARY KEY,
    project_id    INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    task_type     TEXT NOT NULL DEFAULT 'project',  -- 'project' | 'urgent' | 'backlog'
    title         TEXT NOT NULL,
    assignee      TEXT,
    is_done       BOOLEAN NOT NULL DEFAULT FALSE,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_by  TEXT,
    completed_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS task_comments (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    author      TEXT,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_chat (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sender      TEXT,
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


# Idempotent upgrades for databases created with an earlier schema version.
_MIGRATIONS = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';

-- Allow deleting a user without orphan-FK errors on projects they created.
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_created_by_fkey;
ALTER TABLE projects ADD CONSTRAINT projects_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE SET NULL;
"""

# Seeded only when the users table is empty (or a legacy row has no password),
# so the team can never be locked out. Change these passwords from the UI.
_DEFAULT_ADMINS = {"Harel": "harel2026", "Yitzhak": "yitzhak2026"}


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@st.cache_resource(show_spinner="Connecting to database...")
def init_db() -> bool:
    """Create/upgrade tables and seed default admins if needed. Runs once per server process."""
    with get_cursor() as cur:
        cur.execute(_SCHEMA)
        cur.execute(_MIGRATIONS)
        cur.execute("SELECT COUNT(*) AS n FROM users")
        if cur.fetchone()["n"] == 0:
            for username, password in _DEFAULT_ADMINS.items():
                cur.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')",
                    (username, sha256_hex(password)),
                )
        else:
            # Lockout protection: legacy rows seeded before password_hash existed.
            for username, password in _DEFAULT_ADMINS.items():
                cur.execute(
                    "UPDATE users SET password_hash = %s, role = 'admin' "
                    "WHERE username = %s AND password_hash IS NULL",
                    (sha256_hex(password), username),
                )
    return True


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def get_users() -> list[str]:
    with get_cursor() as cur:
        cur.execute("SELECT username FROM users ORDER BY username")
        return [row["username"] for row in cur.fetchall()]


def get_user(username: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return cur.fetchone()


def get_users_detailed() -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT username, role, created_at FROM users ORDER BY created_at")
        return cur.fetchall()


def add_user(username: str, password_hash: str, role: str = "user") -> bool:
    """Create a user. Returns False if the username already exists."""
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, password_hash, role),
            )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def set_user_password(username: str, password_hash: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE username = %s",
            (password_hash, username),
        )


def delete_user(username: str) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (username,))


def count_admins() -> int:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
        return cur.fetchone()["n"]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def get_projects() -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY created_at")
        return cur.fetchall()


def get_project(project_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        return cur.fetchone()


def add_project(name: str, user: str) -> int | None:
    """Create a project (identity-tagged). Returns new id, or None if the name already exists."""
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO projects (name, created_by) VALUES (%s, %s) RETURNING id",
                (name, user),
            )
            project_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO specs (project_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (project_id,),
            )
            return project_id
    except psycopg2.errors.UniqueViolation:
        return None


# ---------------------------------------------------------------------------
# Specs (Module A)
# ---------------------------------------------------------------------------


def get_spec(project_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO specs (project_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (project_id,),
        )
        cur.execute("SELECT * FROM specs WHERE project_id = %s", (project_id,))
        return cur.fetchone()


def save_spec(project_id: int, content: str, user: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO specs (project_id, content, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (project_id)
            DO UPDATE SET content = EXCLUDED.content,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = NOW()
            """,
            (project_id, content, user),
        )


# ---------------------------------------------------------------------------
# Tasks (Module B + Urgent/Backlog pages)
# ---------------------------------------------------------------------------


def get_tasks(project_id: int | None = None, task_type: str = "project") -> list[dict]:
    with get_cursor() as cur:
        if project_id is not None:
            cur.execute(
                "SELECT * FROM tasks WHERE project_id = %s ORDER BY is_done, created_at DESC",
                (project_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM tasks WHERE task_type = %s AND project_id IS NULL "
                "ORDER BY is_done, created_at DESC",
                (task_type,),
            )
        return cur.fetchall()


def add_task(
    title: str,
    assignee: str,
    user: str,
    project_id: int | None = None,
    task_type: str = "project",
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (project_id, task_type, title, assignee, created_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, task_type, title, assignee, user),
        )


def set_task_done(task_id: int, done: bool, user: str) -> None:
    with get_cursor() as cur:
        if done:
            cur.execute(
                "UPDATE tasks SET is_done = TRUE, completed_by = %s, completed_at = NOW() "
                "WHERE id = %s",
                (user, task_id),
            )
        else:
            cur.execute(
                "UPDATE tasks SET is_done = FALSE, completed_by = NULL, completed_at = NULL "
                "WHERE id = %s",
                (task_id,),
            )


def delete_task(task_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))


# ---------------------------------------------------------------------------
# Task comments (nested notes per task)
# ---------------------------------------------------------------------------


def get_comments(task_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM task_comments WHERE task_id = %s ORDER BY created_at",
            (task_id,),
        )
        return cur.fetchall()


def add_comment(task_id: int, content: str, user: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO task_comments (task_id, author, content) VALUES (%s, %s, %s)",
            (task_id, user, content),
        )


# ---------------------------------------------------------------------------
# Project chat (Module C)
# ---------------------------------------------------------------------------


def get_chat(project_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM project_chat WHERE project_id = %s ORDER BY created_at",
            (project_id,),
        )
        return cur.fetchall()


def add_chat_message(project_id: int, message: str, user: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO project_chat (project_id, sender, message) VALUES (%s, %s, %s)",
            (project_id, user, message),
        )
