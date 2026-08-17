"""
database.py — All data access for the Team Dashboard.

Connects to a cloud PostgreSQL database (Supabase) using credentials from
st.secrets.

Performance design:
  * A ThreadedConnectionPool is created once per server process
    (@st.cache_resource) and every query borrows a warm connection — no
    TCP/TLS handshake per rerun. Thread-safe for concurrent sessions.
  * Read queries are cached with @st.cache_data (short TTLs) and every write
    explicitly clears the caches it invalidates, so a user always sees their
    own change immediately; a teammate's changes appear within the TTL or on
    the sidebar 🔄 Refresh (which clears all data caches).
"""

import hashlib
from contextlib import contextmanager

import psycopg2
import psycopg2.errors
import streamlit as st
from psycopg2 import pool as pgpool
from psycopg2.extras import RealDictCursor

VOLATILE_TTL = 10  # seconds — specs, tasks, comments, chat (edited often)
STABLE_TTL = 60    # seconds — project & user lists (edited rarely)

# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _get_pool() -> pgpool.ThreadedConnectionPool:
    """One connection pool per server process, shared safely across sessions/threads."""
    cfg = st.secrets["database"]
    return pgpool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        sslmode="require",
        connect_timeout=10,
        # Keep pooled connections alive so Supabase/network doesn't silently drop them.
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )


@contextmanager
def get_cursor():
    """Yield a dict-cursor inside a transaction on a pooled connection.

    Commits on success, rolls back on error. Broken connections are closed and
    discarded from the pool instead of being handed out again.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        if conn.closed:  # stale connection left in the pool — swap for a fresh one
            p.putconn(conn, close=True)
            conn = p.getconn()
        with conn:  # transaction scope: commit/rollback
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    except psycopg2.OperationalError:
        conn.close()  # connection died mid-query — make sure the pool discards it
        raise
    finally:
        p.putconn(conn, close=bool(conn.closed))


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT,
    role           TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user'
    email          TEXT,                           -- notifications
    phone          TEXT,                           -- notifications (WhatsApp)
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
    is_urgent     BOOLEAN NOT NULL DEFAULT FALSE,
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
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;

-- Allow deleting a user without orphan-FK errors on projects they created,
-- and let a username change cascade to the projects they created.
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_created_by_fkey;
ALTER TABLE projects ADD CONSTRAINT projects_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(username)
    ON DELETE SET NULL ON UPDATE CASCADE;
"""

# Every column that stores a username as identity-tagging metadata. Renaming a
# user rewrites all of them so historical attribution is never orphaned.
# These are hard-coded table/column literals — never user input.
_IDENTITY_COLUMNS = (
    ("projects", "created_by"),
    ("specs", "updated_by"),
    ("tasks", "assignee"),
    ("tasks", "created_by"),
    ("tasks", "completed_by"),
    ("task_comments", "author"),
    ("project_chat", "sender"),
)

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


@st.cache_data(ttl=STABLE_TTL, show_spinner=False)
def get_users() -> list[str]:
    with get_cursor() as cur:
        cur.execute("SELECT username FROM users ORDER BY username")
        return [row["username"] for row in cur.fetchall()]


def get_user(username: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return cur.fetchone()


@st.cache_data(ttl=STABLE_TTL, show_spinner=False)
def get_users_detailed() -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT username, role, email, phone, created_at FROM users ORDER BY created_at"
        )
        return cur.fetchall()


@st.cache_data(ttl=STABLE_TTL, show_spinner=False)
def get_contacts() -> dict[str, dict]:
    """username -> {'email': ..., 'phone': ...} for the notification system."""
    with get_cursor() as cur:
        cur.execute("SELECT username, email, phone FROM users")
        return {
            row["username"]: {"email": row["email"], "phone": row["phone"]}
            for row in cur.fetchall()
        }


def set_user_contact(username: str, email: str | None, phone: str | None) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET email = %s, phone = %s WHERE username = %s",
            (email or None, phone or None, username),
        )
    _clear_user_caches()


def _clear_user_caches() -> None:
    get_users.clear()
    get_users_detailed.clear()
    get_contacts.clear()


def clear_all_caches() -> None:
    """Clear every cached reader (used after a change that touches many tables)."""
    for cached in (
        get_users, get_users_detailed, get_contacts, get_projects, get_project,
        get_spec, get_tasks, get_comments_map, get_chat,
    ):
        cached.clear()


def username_exists(username: str, exclude: str | None = None) -> bool:
    """Case-insensitive existence check, optionally ignoring one existing name."""
    with get_cursor() as cur:
        if exclude is not None:
            cur.execute(
                "SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s) AND username <> %s",
                (username, exclude),
            )
        else:
            cur.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        return cur.fetchone() is not None


def rename_user(old_username: str, new_username: str) -> int | None:
    """Rename a user and re-attribute all of their historical actions.

    Runs as a single transaction, in an order that satisfies the foreign key
    on projects.created_by without depending on ON UPDATE CASCADE (so it also
    works on a database whose schema was created by hand):

        1. copy the users row under the new name (password, role, created_at),
        2. repoint every identity column to the new name,
        3. delete the old users row.

    Returns the number of re-attributed rows, or None if the new name is
    already taken / the old user no longer exists.
    """
    try:
        with get_cursor() as cur:
            reattributed = 0
            for table, column in _IDENTITY_COLUMNS:
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s",  # noqa: S608
                    (old_username,),
                )
                reattributed += cur.fetchone()["n"]

            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, email, phone, created_at)
                SELECT %s, password_hash, role, email, phone, created_at
                FROM users WHERE username = %s
                """,
                (new_username, old_username),
            )
            if cur.rowcount == 0:
                return None  # user disappeared (e.g. deleted by the other admin)

            for table, column in _IDENTITY_COLUMNS:
                cur.execute(
                    f"UPDATE {table} SET {column} = %s WHERE {column} = %s",  # noqa: S608
                    (new_username, old_username),
                )

            cur.execute("DELETE FROM users WHERE username = %s", (old_username,))
    except psycopg2.errors.UniqueViolation:
        return None

    clear_all_caches()
    return reattributed


def add_user(username: str, password_hash: str, role: str = "user") -> bool:
    """Create a user. Returns False if the username already exists."""
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, password_hash, role),
            )
        _clear_user_caches()
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
    _clear_user_caches()


def count_admins() -> int:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
        return cur.fetchone()["n"]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@st.cache_data(ttl=STABLE_TTL, show_spinner=False)
def get_projects() -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY created_at")
        return cur.fetchall()


@st.cache_data(ttl=STABLE_TTL, show_spinner=False)
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
        get_projects.clear()
        return project_id
    except psycopg2.errors.UniqueViolation:
        return None


def delete_project(project_id: int) -> None:
    """Remove a project and (via ON DELETE CASCADE) its spec, tasks, comments and chat."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    get_projects.clear()
    get_project.clear()
    get_spec.clear()
    get_tasks.clear()
    get_comments_map.clear()
    get_chat.clear()


# ---------------------------------------------------------------------------
# Specs (Module A)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
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
    get_spec.clear()


# ---------------------------------------------------------------------------
# Tasks (Module B + Urgent/Backlog pages)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_tasks(project_id: int | None = None, task_type: str = "project") -> list[dict]:
    # Open before done, urgent before regular, newest first.
    order = "ORDER BY is_done, is_urgent DESC, created_at DESC"
    with get_cursor() as cur:
        if project_id is not None:
            cur.execute(
                f"SELECT * FROM tasks WHERE project_id = %s {order}",  # noqa: S608
                (project_id,),
            )
        else:
            cur.execute(
                f"SELECT * FROM tasks WHERE task_type = %s AND project_id IS NULL {order}",  # noqa: S608
                (task_type,),
            )
        return cur.fetchall()


def add_task(
    title: str,
    assignee: str,
    user: str,
    project_id: int | None = None,
    task_type: str = "project",
    is_urgent: bool = False,
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (project_id, task_type, title, assignee, created_by, is_urgent)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (project_id, task_type, title, assignee, user, is_urgent),
        )
    get_tasks.clear()


def set_task_urgent(task_id: int, urgent: bool) -> None:
    with get_cursor() as cur:
        cur.execute("UPDATE tasks SET is_urgent = %s WHERE id = %s", (urgent, task_id))
    get_tasks.clear()


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
    get_tasks.clear()


def delete_task(task_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    get_tasks.clear()
    get_comments_map.clear()


# ---------------------------------------------------------------------------
# Task comments (nested notes per task)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_comments_map(
    project_id: int | None = None, task_type: str = "project"
) -> dict[int, list[dict]]:
    """All comments for every task in scope, in ONE query (instead of one per task)."""
    with get_cursor() as cur:
        if project_id is not None:
            cur.execute(
                "SELECT c.* FROM task_comments c JOIN tasks t ON t.id = c.task_id "
                "WHERE t.project_id = %s ORDER BY c.created_at",
                (project_id,),
            )
        else:
            cur.execute(
                "SELECT c.* FROM task_comments c JOIN tasks t ON t.id = c.task_id "
                "WHERE t.task_type = %s AND t.project_id IS NULL ORDER BY c.created_at",
                (task_type,),
            )
        comments_map: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            comments_map.setdefault(row["task_id"], []).append(row)
        return comments_map


def add_comment(task_id: int, content: str, user: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO task_comments (task_id, author, content) VALUES (%s, %s, %s)",
            (task_id, user, content),
        )
    get_comments_map.clear()


# ---------------------------------------------------------------------------
# Project chat (Module C)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
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
    get_chat.clear()
