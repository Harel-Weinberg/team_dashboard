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
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from contextlib import contextmanager
from datetime import date, datetime

import psycopg2
import psycopg2.errors
import streamlit as st

import perf
from psycopg2 import pool as pgpool
from psycopg2.extras import RealDictCursor

# TTLs tuned for navigation speed. Staleness is bounded anyway: every write
# clears the caches it touches (own changes are always instant), and 🔄 Refresh
# clears everything — the TTL only caps how old a TEAMMATE's change can look.
VOLATILE_TTL = 30   # seconds — specs, tasks, comments
STABLE_TTL = 120    # seconds — project & user lists
# Chat is polled by a 500ms fragment. Both TTLs below must stay SHORTER than
# that poll interval, or the poller just re-serves cache and the "live" chat
# isn't live. WATERMARK_TTL doubles as the ceiling on how many full message
# fetches a single poll cadence can force — see get_chat_watermark().
CHAT_TTL = 0.25         # seconds — full message list
WATERMARK_TTL = 0.25    # seconds — max(created_at) probe

# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Thread discipline (see optimistic.py)
#
# Background workers must not call into Streamlit: st.secrets, st.session_state
# and the st.cache_* APIs all expect a ScriptRunContext, and a worker has none.
# Two mechanisms keep that true:
#
#   * the pool object is resolved ONCE on the render thread and kept in a plain
#     module global, so get_cursor() on a worker touches no st.* API at all;
#   * cache invalidation from a worker is queued and drained by the render
#     thread on its next rerun (_invalidate / drain_deferred_invalidations).
#
# Worker threads are identified by name — the pools below set the prefixes.
# ---------------------------------------------------------------------------

_WORKER_PREFIXES = ("db-sync", "db-prefetch")

_POOL: pgpool.ThreadedConnectionPool | None = None
_DEFERRED_CLEARS: list[tuple] = []
_DEFERRED_LOCK = threading.Lock()


def on_worker_thread() -> bool:
    return threading.current_thread().name.startswith(_WORKER_PREFIXES)


def _invalidate(*cached_fns) -> None:
    """Clear cached readers — immediately on the render thread, deferred on a worker."""
    if on_worker_thread():
        with _DEFERRED_LOCK:
            _DEFERRED_CLEARS.append(cached_fns)
        return
    for fn in cached_fns:
        fn.clear()


def drain_deferred_invalidations() -> int:
    """Apply cache clears queued by worker threads. Render thread only."""
    with _DEFERRED_LOCK:
        pending = list(_DEFERRED_CLEARS)
        _DEFERRED_CLEARS.clear()
    for group in pending:
        for fn in group:
            fn.clear()
    return len(pending)


def ensure_pool() -> pgpool.ThreadedConnectionPool:
    """Resolve the pool on the render thread and cache it in a plain global.

    Called from main() before anything can dispatch background work, so a
    worker never has to reach through st.cache_resource / st.secrets itself.
    """
    global _POOL
    if _POOL is None:
        _POOL = _create_pool()
    return _POOL


@st.cache_resource(show_spinner=False)
def _create_pool() -> pgpool.ThreadedConnectionPool:
    """One connection pool per server process, shared safely across sessions/threads."""
    cfg = st.secrets["database"]
    # minconn=4: the pool opens (and TLS-handshakes) these eagerly at startup.
    # Opening connections on demand mid-navigation is poison: N simultaneous
    # TLS handshakes serialize on the GIL and turn 180ms queries into seconds.
    return pgpool.ThreadedConnectionPool(
        minconn=4,
        maxconn=12,
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
    p = _POOL if _POOL is not None else ensure_pool()
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

-- Per-user read state, generic across the two things that carry an unread
-- count: a project's chat (scope_type='project_chat', scope_id=project_id)
-- and a single task's comment thread (scope_type='task_comments',
-- scope_id=task_id). No FK on scope_id — it points at different tables
-- depending on scope_type — so cleanup on delete is explicit (see
-- delete_project/delete_task) rather than ON DELETE CASCADE.
CREATE TABLE IF NOT EXISTS read_receipts (
    username      TEXT NOT NULL,
    scope_type    TEXT NOT NULL,
    scope_id      INTEGER NOT NULL,
    last_read_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, scope_type, scope_id)
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

-- Forward-compatibility for the planned kanban board. Purely additive: is_done
-- stays the source of truth and nothing reads these columns yet — they exist so
-- adding the board later is a code change, not a second database migration.
--
-- The column is added WITHOUT a default so pre-existing rows land as NULL and
-- the backfill below can target them precisely. Re-running this on every boot
-- must never clobber a real status, so the backfill is guarded on IS NULL; the
-- default is attached afterwards, for rows inserted from here on.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status TEXT;
UPDATE tasks SET status = CASE WHEN is_done THEN 'done' ELSE 'todo' END
 WHERE status IS NULL;
ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'todo';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date DATE;

-- The kanban board arrived: status is now a real, user-facing 3-state field
-- (replacing the boolean checkbox in the UI), with Hebrew values instead of
-- the placeholder English ones above. is_done remains internally in sync
-- (is_done = status = 'בוצע') so the notification triggers, the urgent-tasks
-- widget and the mailto helper — all keyed on is_done, all already tested —
-- needed no changes. Each UPDATE only ever touches rows still holding the
-- OLD value, so this block is naturally idempotent on every boot.
UPDATE tasks SET status = 'בתהליך' WHERE status = 'todo';
UPDATE tasks SET status = 'בוצע'   WHERE status = 'done';
UPDATE tasks SET status = 'בתהליך' WHERE status = 'in_progress';
UPDATE tasks SET status = 'בבירור' WHERE status = 'review';
ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'בתהליך';

-- Task board revamp: rich task details, additive only.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';
-- Attachments are stored as bytes in Postgres rather than in Supabase
-- Storage: this app has no Storage bucket, policy, client library or extra
-- secret configured, and task attachments in a small internal tool are a
-- handful of small PDFs/screenshots — not worth a second storage system and
-- a new external dependency for that. attachment_data is capped client-side
-- (see ui_components.MAX_ATTACHMENT_BYTES) before it ever reaches a write.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_name TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_type TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_data BYTEA;

-- Optimistic-send reconciliation: the client mints a uuid4 per message so a
-- local echo can be matched to its server row exactly, instead of comparing
-- sender+body text. The partial unique index below also makes the INSERT
-- idempotent, so a retried write cannot double-post.
ALTER TABLE project_chat ADD COLUMN IF NOT EXISTS client_msg_id TEXT;

-- chat_reads (a first attempt at read tracking, project-chat-only, never
-- wired into any application code) is superseded by the generic
-- read_receipts table above, which also covers task comment threads.
-- Safe to drop outright: zero rows, zero code ever read or wrote it.
DROP TABLE IF EXISTS chat_reads;

-- Urgency becomes a 3-level field (נמוך/בינוני/גבוה) instead of a boolean,
-- to match the status dropdown's UI pattern. is_urgent remains as an
-- internal mirror (is_urgent = urgency = 'גבוה') for the exact same reason
-- status kept is_done in sync: get_urgent_open_tasks(), the home-screen
-- urgent widget, the urgent-task sort order, and notify_urgent_assignment()
-- are all keyed on is_urgent and already tested — "not flagged urgent"
-- maps to the neutral middle level, not the bottom one, since that was the
-- implicit default every task had before this column existed.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS urgency TEXT;
UPDATE tasks SET urgency = CASE WHEN is_urgent THEN 'גבוה' ELSE 'בינוני' END
 WHERE urgency IS NULL;
ALTER TABLE tasks ALTER COLUMN urgency SET DEFAULT 'בינוני';
"""


# Indexes matching the access patterns in this module. Negligible at today's row
# counts; they exist so the query plans stay flat as the tables grow.
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_chat_project_time
    ON project_chat (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_project  ON tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_task_assignee ON tasks (assignee);
CREATE INDEX IF NOT EXISTS idx_task_status   ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_comment_task  ON task_comments (task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_client_msg
    ON project_chat (client_msg_id) WHERE client_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_read_receipts_scope
    ON read_receipts (scope_type, scope_id);
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
    ("read_receipts", "username"),
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
        cur.execute(_INDEXES)
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
    _invalidate(get_users, get_users_detailed, get_contacts)


def clear_all_caches() -> None:
    """Clear every cached reader (used after a change that touches many tables)."""
    _invalidate(
        get_users, get_users_detailed, get_contacts, get_projects,
        _project_bundle, _board_tasks, _board_comments, get_urgent_open_tasks,
        get_chat, get_task_attachment, get_open_task_counts,
        get_chat_unread_counts, get_task_comment_unread_counts,
        get_unread_counts_for_tasks,
    )


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
        # Unlike other identity columns (tasks.assignee, project_chat.sender,
        # ...), a deleted user's read-state has no historical value worth
        # keeping as a dangling row — clean it up. This is the one identity
        # column where "orphaned" isn't the intended, established behavior.
        cur.execute("DELETE FROM read_receipts WHERE username = %s", (username,))
        cur.execute("DELETE FROM users WHERE username = %s", (username,))
    _clear_user_caches()
    _invalidate(get_chat_unread_counts, get_task_comment_unread_counts, get_unread_counts_for_tasks)


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


def _revive(row: dict | None) -> dict | None:
    """row_to_json turns timestamptz/date into ISO strings — convert them back."""
    if row is None:
        return None
    for key, value in row.items():
        if key.endswith("_at") and isinstance(value, str):
            row[key] = datetime.fromisoformat(value)
        elif key == "due_date" and isinstance(value, str):
            row[key] = date.fromisoformat(value)
    return row


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
@perf.track("db:bundle_query")
def _project_bundle(project_id: int) -> dict:
    """Everything the project dashboard shows, in ONE database round-trip.

    Navigation used to fire ~5 sequential queries (project, spec, tasks,
    comments, chat) at ~180ms each. Fetching them in parallel is worse, not
    better — concurrent TLS handshakes serialize on the GIL — so instead the
    whole payload is aggregated to JSON server-side and fetched in a single
    statement on one warm pooled connection.

    Chat is deliberately NOT part of this bundle. It is polled every 3s by the
    chat fragment and needs a ~2s TTL; keeping it here would drag spec, tasks
    and comments down to that TTL too, and — worse — every sent message would
    invalidate the whole bundle and make the next render block on a full
    refetch. See get_chat().
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT row_to_json(p) FROM projects p WHERE p.id = %(pid)s) AS project,
              (SELECT row_to_json(s) FROM specs s WHERE s.project_id = %(pid)s) AS spec,
              (SELECT COALESCE(json_agg(to_jsonb(t) - 'attachment_data'
                       ORDER BY t.is_done, t.is_urgent DESC, t.created_at DESC), '[]'::json)
                 FROM tasks t WHERE t.project_id = %(pid)s) AS tasks,
              (SELECT COALESCE(json_agg(row_to_json(c) ORDER BY c.created_at), '[]'::json)
                 FROM task_comments c JOIN tasks t ON t.id = c.task_id
                WHERE t.project_id = %(pid)s) AS comments
            """,
            {"pid": project_id},
        )
        raw = cur.fetchone()

        spec = _revive(raw["spec"])
        if spec is None and raw["project"] is not None:
            # Legacy project without a spec row — create it once, off the hot path.
            cur.execute(
                "INSERT INTO specs (project_id) VALUES (%s) ON CONFLICT DO NOTHING "
                "RETURNING *",
                (project_id,),
            )
            spec = dict(cur.fetchone())

    comments_map: dict[int, list[dict]] = {}
    for comment in raw["comments"]:
        comments_map.setdefault(comment["task_id"], []).append(_revive(comment))

    return {
        "project": _revive(raw["project"]),
        "spec": spec,
        "tasks": [_revive(t) for t in raw["tasks"]],
        "comments_map": comments_map,
    }


def get_project(project_id: int) -> dict | None:
    return _project_bundle(project_id)["project"]


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
        _invalidate(get_projects)
        return project_id
    except psycopg2.errors.UniqueViolation:
        return None


def delete_project(project_id: int) -> None:
    """Remove a project and (via ON DELETE CASCADE) its spec, tasks, comments and chat."""
    with get_cursor() as cur:
        # read_receipts has no FK on scope_id (it points at different tables
        # depending on scope_type), so it doesn't get an automatic CASCADE —
        # clean up this project's chat read-state explicitly. Task-comment
        # read-state cascades on its own via the task delete below.
        cur.execute(
            "DELETE FROM read_receipts WHERE scope_type = %s AND scope_id = %s",
            (SCOPE_PROJECT_CHAT, project_id),
        )
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    _invalidate(get_projects, get_chat_unread_counts)
    _clear_task_caches()  # also clears _project_bundle (spec/comments/chat included)


# ---------------------------------------------------------------------------
# Specs (Module A)
# ---------------------------------------------------------------------------


def get_spec(project_id: int) -> dict:
    return _project_bundle(project_id)["spec"]


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
    _invalidate(_project_bundle)


# ---------------------------------------------------------------------------
# Tasks (Module B + Urgent/Backlog pages)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def _board_tasks(task_type: str) -> list[dict]:
    """Tasks of the global boards (urgent / backlog) — not tied to a project.

    Explicit column list, NOT `SELECT *` — same reason as
    get_urgent_open_tasks(): this is @st.cache_data-cached, which pickles the
    return value, and attachment_data (bytea) comes back as an unpicklable
    memoryview. No ad-hoc task currently has an attachment, but the add-task
    form allows uploading one for any task_type, so this was one upload away
    from crashing these two pages the same way.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, task_type, title, assignee, is_done,
                   created_by, created_at, completed_by, completed_at,
                   is_urgent, status, due_date, description, tags,
                   attachment_name, attachment_type, urgency
            FROM tasks WHERE task_type = %s AND project_id IS NULL
            ORDER BY is_done, is_urgent DESC, created_at DESC
            """,
            (task_type,),
        )
        return cur.fetchall()


def get_tasks(project_id: int | None = None, task_type: str = "project") -> list[dict]:
    if project_id is not None:
        return _project_bundle(project_id)["tasks"]
    return _board_tasks(task_type)


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_task_attachment(task_id: int) -> tuple[str, str, bytes] | None:
    """(filename, mime_type, raw_bytes) for one task's attachment, or None.

    Deliberately NOT part of _project_bundle: row_to_json() encodes bytea as
    a hex string rather than real bytes, and even fixed, folding a multi-MB
    blob into the one JSON payload every task-list read fetches would bloat
    the hot path for every task in the project, not just the one being
    downloaded. This is a targeted, indexed single-row lookup instead,
    fetched only when a card with an attachment actually renders its
    download button.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT attachment_name, attachment_type, attachment_data "
            "FROM tasks WHERE id = %s AND attachment_data IS NOT NULL",
            (task_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return row["attachment_name"], row["attachment_type"], bytes(row["attachment_data"])


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_urgent_open_tasks() -> list[dict]:
    """All open urgent tasks across every project, for the home-screen widget.

    One query with the project name joined in; cached like the other task
    reads and cleared by every task write.

    Explicit column list, NOT `t.*`: this result is cached with
    @st.cache_data, which pickles the return value, and psycopg2 returns
    attachment_data (bytea) as a memoryview — unpicklable, so `t.*` here
    crashes the whole home page the moment any urgent+open task anywhere
    has an attachment (confirmed live: a real production task did). The
    widget never needs the attachment bytes anyway — it only checks
    attachment_name to decide whether to show anything about it at all.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.project_id, t.task_type, t.title, t.assignee, t.is_done,
                   t.created_by, t.created_at, t.completed_by, t.completed_at,
                   t.is_urgent, t.status, t.due_date, t.description, t.tags,
                   t.attachment_name, t.attachment_type, t.urgency,
                   p.name AS project_name
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.is_urgent AND NOT t.is_done
            ORDER BY t.created_at DESC
            """
        )
        return cur.fetchall()


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_open_task_counts() -> dict[int, int]:
    """project_id -> count of open (not done) tasks, for the home-screen
    project cards' activity summary. One query, every project at once."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT project_id, COUNT(*) AS n FROM tasks "
            "WHERE project_id IS NOT NULL AND NOT is_done "
            "GROUP BY project_id"
        )
        return {row["project_id"]: row["n"] for row in cur.fetchall()}


def _clear_task_caches() -> None:
    _invalidate(
        _project_bundle, _board_tasks, _board_comments, get_urgent_open_tasks,
        get_task_attachment, get_open_task_counts,
    )


# Public alias — tests and callers shouldn't reach for the underscore name.
clear_task_caches = _clear_task_caches


# The task board's 3-state field. is_done is kept as an internal mirror
# (is_done = status == STATUS_DONE) purely so notifications, the urgent-tasks
# widget and the mailto helper — all keyed on is_done, all already tested —
# never had to be touched for this. Both non-done statuses map to
# is_done=False, which is exactly the "open task" grouping those consumers
# already expect.
STATUS_IN_PROGRESS = "בתהליך"
STATUS_IN_REVIEW = "בבירור"
STATUS_DONE = "בוצע"
TASK_STATUSES = (STATUS_IN_PROGRESS, STATUS_IN_REVIEW, STATUS_DONE)

# Urgency: a 3-level field mirrored onto the boolean is_urgent
# (is_urgent = urgency == URGENCY_HIGH) — see the _MIGRATIONS comment for why.
URGENCY_LOW = "נמוך"
URGENCY_MEDIUM = "בינוני"
URGENCY_HIGH = "גבוה"
TASK_URGENCY_LEVELS = (URGENCY_LOW, URGENCY_MEDIUM, URGENCY_HIGH)


def add_task(
    title: str,
    assignee: str,
    user: str,
    project_id: int | None = None,
    task_type: str = "project",
    is_urgent: bool = False,
    *,
    description: str = "",
    due_date: date | None = None,
    tags: list[str] | None = None,
    attachment: tuple[str, str, bytes] | None = None,
) -> None:
    """`attachment` is (filename, mime_type, raw_bytes), or None."""
    att_name, att_type, att_data = attachment if attachment else (None, None, None)
    # Mirror is_urgent -> urgency the same way set_task_urgent does — without
    # this, a task created with is_urgent=True would land on urgency's column
    # DEFAULT ('בינוני') instead, inconsistent with is_urgent=True from the
    # moment it's created.
    urgency = URGENCY_HIGH if is_urgent else URGENCY_MEDIUM
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (
                project_id, task_type, title, assignee, created_by, is_urgent, urgency,
                description, due_date, tags, attachment_name, attachment_type, attachment_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id, task_type, title, assignee, user, is_urgent, urgency,
                description, due_date, tags or [], att_name, att_type,
                psycopg2.Binary(att_data) if att_data else None,
            ),
        )
    _clear_task_caches()


def set_task_urgent(task_id: int, urgent: bool) -> None:
    """Boolean compatibility entry point. Also keeps `urgency` in sync:
    True -> URGENCY_HIGH, False -> URGENCY_MEDIUM (a task lowered this way
    always lands on the neutral middle level, never URGENCY_LOW — that
    finer distinction only exists via set_task_urgency, the dropdown's own
    write path).
    """
    urgency = URGENCY_HIGH if urgent else URGENCY_MEDIUM
    with get_cursor() as cur:
        cur.execute(
            "UPDATE tasks SET is_urgent = %s, urgency = %s WHERE id = %s",
            (urgent, urgency, task_id),
        )
    _clear_task_caches()


def set_task_urgency(task_id: int, urgency: str) -> None:
    """Primary write path for the urgency dropdown. One atomic UPDATE keeps
    urgency and is_urgent consistent."""
    if urgency not in TASK_URGENCY_LEVELS:
        raise ValueError(f"unknown urgency level: {urgency!r}")
    with get_cursor() as cur:
        cur.execute(
            "UPDATE tasks SET urgency = %s, is_urgent = %s WHERE id = %s",
            (urgency, urgency == URGENCY_HIGH, task_id),
        )
    _clear_task_caches()


def set_task_done(task_id: int, done: bool, user: str) -> None:
    """Boolean compatibility entry point. Also keeps `status` in sync:
    True -> STATUS_DONE, False -> STATUS_IN_PROGRESS (a task reopened this way
    always lands "in progress", never "in review" — that richer distinction
    only exists via set_task_status, the dropdown's own write path).
    """
    with get_cursor() as cur:
        if done:
            cur.execute(
                "UPDATE tasks SET is_done = TRUE, status = %s, "
                "completed_by = %s, completed_at = NOW() WHERE id = %s",
                (STATUS_DONE, user, task_id),
            )
        else:
            cur.execute(
                "UPDATE tasks SET is_done = FALSE, status = %s, "
                "completed_by = NULL, completed_at = NULL WHERE id = %s",
                (STATUS_IN_PROGRESS, task_id),
            )
    _clear_task_caches()


def set_task_status(task_id: int, status: str, user: str) -> None:
    """Primary write path for the status dropdown. One atomic UPDATE keeps
    status and is_done consistent, and sets/clears completed_by/completed_at
    on the same edges set_task_done does.
    """
    if status not in TASK_STATUSES:
        raise ValueError(f"unknown task status: {status!r}")
    done = status == STATUS_DONE
    with get_cursor() as cur:
        if done:
            cur.execute(
                "UPDATE tasks SET status = %s, is_done = TRUE, "
                "completed_by = %s, completed_at = NOW() WHERE id = %s",
                (status, user, task_id),
            )
        else:
            cur.execute(
                "UPDATE tasks SET status = %s, is_done = FALSE, "
                "completed_by = NULL, completed_at = NULL WHERE id = %s",
                (status, task_id),
            )
    _clear_task_caches()


def delete_task(task_id: int) -> None:
    with get_cursor() as cur:
        # Same reasoning as delete_project: read_receipts has no FK, so this
        # task's comment-thread read-state needs an explicit delete too.
        cur.execute(
            "DELETE FROM read_receipts WHERE scope_type = %s AND scope_id = %s",
            (SCOPE_TASK_COMMENTS, task_id),
        )
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    _clear_task_caches()  # comments cascade with the task; _board_comments included


# ---------------------------------------------------------------------------
# Task comments (nested notes per task)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def _board_comments(task_type: str) -> dict[int, list[dict]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT c.* FROM task_comments c JOIN tasks t ON t.id = c.task_id "
            "WHERE t.task_type = %s AND t.project_id IS NULL ORDER BY c.created_at",
            (task_type,),
        )
        comments_map: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            comments_map.setdefault(row["task_id"], []).append(row)
        return comments_map


def get_comments_map(
    project_id: int | None = None, task_type: str = "project"
) -> dict[int, list[dict]]:
    """All comments for every task in scope (one query, part of the bundle)."""
    if project_id is not None:
        return _project_bundle(project_id)["comments_map"]
    return _board_comments(task_type)


def add_comment(task_id: int, content: str, user: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO task_comments (task_id, author, content) VALUES (%s, %s, %s)",
            (task_id, user, content),
        )
    _invalidate(_project_bundle, _board_comments, get_task_comment_unread_counts,
                get_unread_counts_for_tasks)


# ---------------------------------------------------------------------------
# Read receipts (unread badges for project chat + task comment threads)
# ---------------------------------------------------------------------------

SCOPE_PROJECT_CHAT = "project_chat"
SCOPE_TASK_COMMENTS = "task_comments"


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_chat_unread_counts(username: str) -> dict[int, int]:
    """project_id -> count of chat messages from someone else posted after
    this user's last_read_at for that project. One query, every project at
    once — feeds both the home-screen project cards and the chat tab badge.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT c.project_id, COUNT(*) AS n
            FROM project_chat c
            LEFT JOIN read_receipts r
                   ON r.username = %(user)s AND r.scope_type = %(scope)s
                  AND r.scope_id = c.project_id
            WHERE c.sender IS DISTINCT FROM %(user)s
              AND (r.last_read_at IS NULL OR c.created_at > r.last_read_at)
            GROUP BY c.project_id
            """,
            {"user": username, "scope": SCOPE_PROJECT_CHAT},
        )
        return {row["project_id"]: row["n"] for row in cur.fetchall()}


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_task_comment_unread_counts(
    username: str, project_id: int | None = None, task_type: str = "project"
) -> dict[int, int]:
    """task_id -> unread comment count, scoped the same way get_comments_map is."""
    with get_cursor() as cur:
        scope_filter = (
            "t.project_id = %(pid)s" if project_id is not None
            else "t.task_type = %(tt)s AND t.project_id IS NULL"
        )
        cur.execute(
            f"""
            SELECT c.task_id, COUNT(*) AS n
            FROM task_comments c
            JOIN tasks t ON t.id = c.task_id
            LEFT JOIN read_receipts r
                   ON r.username = %(user)s AND r.scope_type = %(scope)s
                  AND r.scope_id = c.task_id
            WHERE {scope_filter}
              AND c.author IS DISTINCT FROM %(user)s
              AND (r.last_read_at IS NULL OR c.created_at > r.last_read_at)
            GROUP BY c.task_id
            """,  # noqa: S608 — scope_filter is one of two hard-coded literals, never user input
            {"user": username, "scope": SCOPE_TASK_COMMENTS, "pid": project_id, "tt": task_type},
        )
        return {row["task_id"]: row["n"] for row in cur.fetchall()}


@st.cache_data(ttl=VOLATILE_TTL, show_spinner=False)
def get_unread_counts_for_tasks(username: str, task_ids: tuple[int, ...]) -> dict[int, int]:
    """Same as get_task_comment_unread_counts, but for an explicit, arbitrary
    set of task ids instead of one (project_id, task_type) scope — for the
    home-screen urgent-tasks widget, whose tasks can span many different
    projects and both ad-hoc task types at once. `task_ids` is a tuple (not
    a list) so it hashes cleanly as an st.cache_data key.
    """
    if not task_ids:
        return {}
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT c.task_id, COUNT(*) AS n
            FROM task_comments c
            LEFT JOIN read_receipts r
                   ON r.username = %(user)s AND r.scope_type = %(scope)s
                  AND r.scope_id = c.task_id
            WHERE c.task_id = ANY(%(ids)s)
              AND c.author IS DISTINCT FROM %(user)s
              AND (r.last_read_at IS NULL OR c.created_at > r.last_read_at)
            GROUP BY c.task_id
            """,
            {"user": username, "scope": SCOPE_TASK_COMMENTS, "ids": list(task_ids)},
        )
        return {row["task_id"]: row["n"] for row in cur.fetchall()}


def mark_scope_read(username: str, scope_type: str, scope_id: int) -> None:
    """Upsert last_read_at = now() for one (username, scope_type, scope_id)."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO read_receipts (username, scope_type, scope_id, last_read_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (username, scope_type, scope_id)
            DO UPDATE SET last_read_at = NOW()
            """,
            (username, scope_type, scope_id),
        )
    _invalidate(get_chat_unread_counts, get_task_comment_unread_counts, get_unread_counts_for_tasks)


# ---------------------------------------------------------------------------
# Project chat (Module C)
# ---------------------------------------------------------------------------


# Rendering shows the whole conversation today (single digits of messages per
# project). The query is newest-first so capping it is a one-line change:
# pass a smaller `limit` and add a "load earlier" control.
CHAT_PAGE = 200


@st.cache_data(ttl=WATERMARK_TTL, show_spinner=False)
@perf.track("db:chat_watermark")
def get_chat_watermark(project_id: int) -> datetime | None:
    """The newest created_at for a project's chat — index-only via idx_chat_project_time.

    Cheap enough to call on every poll tick. The chat fragment calls this
    FIRST and only reaches for the full get_chat() below when the value has
    moved since the last tick, so an idle chat costs one tiny MAX() probe per
    poll instead of a full row fetch.

    st.cache_data is a per-process resource cache, not per-session: N
    sessions polling the SAME project share one cached value, so the real
    query rate against Supabase is bounded by 1/WATERMARK_TTL per actively-
    viewed project, not by the number of connected users.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT max(created_at) AS latest FROM project_chat WHERE project_id = %s",
            (project_id,),
        )
        return cur.fetchone()["latest"]


@st.cache_data(ttl=CHAT_TTL, show_spinner=False)
@perf.track("db:chat_query")
def get_chat(project_id: int, limit: int = CHAT_PAGE) -> list[dict]:
    """The newest `limit` messages for a project, oldest-first for rendering."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM project_chat WHERE project_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (project_id, limit),
        )
        return list(reversed(cur.fetchall()))


def add_chat_message(
    project_id: int, message: str, user: str, client_msg_id: str | None = None
) -> None:
    """Insert a chat message. Safe to retry: a repeated client_msg_id is a no-op.

    Runs on a background worker thread — no st.* calls beyond _invalidate(),
    which defers to the render thread when called off-thread.
    """
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO project_chat (project_id, sender, message, client_msg_id) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (client_msg_id) WHERE client_msg_id IS NOT NULL DO NOTHING",
            (project_id, user, message, client_msg_id),
        )
    _refresh_chat_after_write()
    # Unlike get_chat/get_chat_watermark, unread counts are for OTHER users —
    # staleness here never stalls the sender's own render, so this always
    # invalidates (deferred to the render thread when called from a worker,
    # same as every other task/comment write).
    _invalidate(get_chat_unread_counts)


def _refresh_chat_after_write() -> None:
    """Invalidate the chat cache for a SYNCHRONOUS write only.

    From a background worker there is deliberately nothing to do. The sender is
    already looking at a local echo of their own message, and CHAT_TTL is
    shorter than the fragment's poll interval, so the server copy replaces that
    echo within one tick. Clearing the cache here instead makes the very next
    render block on a full refetch (~185ms against eu-central-1) — measurably
    the stall that the optimistic send path exists to remove.
    """
    if not on_worker_thread():
        get_chat.clear()
        get_chat_watermark.clear()


# ---------------------------------------------------------------------------
# Prefetching — parallel reads & cache warming for fast navigation
# ---------------------------------------------------------------------------


# A deliberately small pool: prefetch concurrency is bounded by the pool's
# eagerly-opened connections (minconn). More workers would only trigger
# on-demand TLS handshakes, which serialize on the GIL and stall everything.
@st.cache_resource(show_spinner=False)
def _prefetch_pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=3, thread_name_prefix="db-prefetch")


def warm_project(project_id: int, wait: bool = True) -> None:
    """Populate the project's bundle cache plus chat and the shared lookups.

    The bundle and the chat are two separate queries but they are issued
    concurrently on the prefetch pool, so opening a project still costs about
    one round-trip of wall-clock rather than two.

    wait=False is fire-and-forget: used from the home screen to silently
    pre-warm projects so clicking a bubble feels instant. Cache hits return in
    microseconds, so re-warming an already-warm project is effectively free.
    Errors are swallowed here — if the DB is down, the renderer's own read
    will surface the failure with proper context.
    """
    jobs = (
        lambda: _project_bundle(project_id),
        lambda: get_chat(project_id),
        lambda: get_contacts(),
        lambda: get_users(),
    )
    futures = [_prefetch_pool().submit(job) for job in jobs]
    if wait:
        futures_wait(futures, timeout=15)
        for f in futures:
            if f.done():
                f.exception()  # retrieve, so failures aren't logged as unhandled


def prefetch_all_projects() -> None:
    """Fire-and-forget warm of every project + the global boards (home screen).

    One bundle query per project — with warm caches this whole call is a no-op.
    """
    try:
        projects = get_projects()
    except psycopg2.Error:
        return
    for project in projects:
        _prefetch_pool().submit(lambda pid=project["id"]: _project_bundle(pid))
    for board in ("urgent", "backlog"):
        _prefetch_pool().submit(lambda b=board: _board_tasks(b))
        _prefetch_pool().submit(lambda b=board: _board_comments(b))
