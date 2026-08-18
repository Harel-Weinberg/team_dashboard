-- =============================================================================
-- schema.sql — Optional: run this once in the Supabase SQL Editor.
-- (The app also creates these tables automatically on first run via init_db(),
--  so this file is only needed if you prefer to set up the schema manually.)
-- =============================================================================

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
    created_by  TEXT REFERENCES users(username) ON DELETE SET NULL,
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

-- --------------------------------------------------------------------------
-- Per-user chat read state (unread badges on the home screen)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_reads (
    username      TEXT NOT NULL,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    last_read_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, project_id)
);

-- Optimistic-send reconciliation id (additive).
ALTER TABLE project_chat ADD COLUMN IF NOT EXISTS client_msg_id TEXT;

-- --------------------------------------------------------------------------
-- Forward-compatibility columns for the planned kanban board (additive only —
-- is_done remains the source of truth; no code reads these yet).
-- --------------------------------------------------------------------------
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status TEXT;
UPDATE tasks SET status = CASE WHEN is_done THEN 'done' ELSE 'todo' END
 WHERE status IS NULL;
ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'todo';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date DATE;

-- --------------------------------------------------------------------------
-- Indexes
-- --------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chat_project_time
    ON project_chat (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_project  ON tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_task_assignee ON tasks (assignee);
CREATE INDEX IF NOT EXISTS idx_comment_task  ON task_comments (task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_client_msg
    ON project_chat (client_msg_id) WHERE client_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_reads_user ON chat_reads (username);

-- Default admin seeding (dummy passwords 'harel2026' / 'yitzhak2026') is done
-- automatically by the app's init_db() when the users table is empty.
-- Change these passwords from the User Management page after first login.
