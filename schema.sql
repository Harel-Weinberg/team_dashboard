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
-- Per-user read state, generic across project chat and task comment threads
-- (unread badges). No FK on scope_id since it points at different tables
-- depending on scope_type; cleanup on delete is explicit in application code.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS read_receipts (
    username      TEXT NOT NULL,
    scope_type    TEXT NOT NULL,
    scope_id      INTEGER NOT NULL,
    last_read_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, scope_type, scope_id)
);

-- Optimistic-send reconciliation id (additive).
ALTER TABLE project_chat ADD COLUMN IF NOT EXISTS client_msg_id TEXT;

-- --------------------------------------------------------------------------
-- Task board revamp: status is now a real 3-state field (בתהליך / בבירור /
-- בוצע), replacing the boolean checkbox in the UI. is_done stays in sync
-- (is_done = status = 'בוצע') so notifications/urgent-widget/mailto — all
-- keyed on is_done — needed no changes. Each UPDATE only touches rows still
-- holding an older value, so this whole block is idempotent.
-- --------------------------------------------------------------------------
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status TEXT;
UPDATE tasks SET status = CASE WHEN is_done THEN 'done' ELSE 'todo' END
 WHERE status IS NULL;
UPDATE tasks SET status = 'בתהליך' WHERE status = 'todo';
UPDATE tasks SET status = 'בוצע'   WHERE status = 'done';
UPDATE tasks SET status = 'בתהליך' WHERE status = 'in_progress';
UPDATE tasks SET status = 'בבירור' WHERE status = 'review';
ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'בתהליך';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

-- Attachments are stored as bytes in Postgres, not Supabase Storage — no
-- Storage bucket/policy/client is configured for this app, and task
-- attachments here are a handful of small PDFs/screenshots. Size is capped
-- client-side (see ui_components.MAX_ATTACHMENT_BYTES) before any write.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_name TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_type TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachment_data BYTEA;

-- --------------------------------------------------------------------------
-- Urgency becomes a 3-level field (נמוך / בינוני / גבוה) instead of a
-- boolean. is_urgent stays in sync (is_urgent = urgency = 'גבוה') for the
-- same reason status kept is_done in sync — get_urgent_open_tasks(), the
-- home-screen urgent widget and notify_urgent_assignment() are all keyed
-- on is_urgent and already tested. "Not flagged urgent" maps to the
-- neutral middle level, since that was every task's implicit default
-- before this column existed.
-- --------------------------------------------------------------------------
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS urgency TEXT;
UPDATE tasks SET urgency = CASE WHEN is_urgent THEN 'גבוה' ELSE 'בינוני' END
 WHERE urgency IS NULL;
ALTER TABLE tasks ALTER COLUMN urgency SET DEFAULT 'בינוני';

-- chat_reads (project-chat-only, never wired into any application code) is
-- superseded by read_receipts above, which also covers task comments.
DROP TABLE IF EXISTS chat_reads;

-- --------------------------------------------------------------------------
-- Indexes
-- --------------------------------------------------------------------------
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

-- Default admin seeding (dummy passwords 'harel2026' / 'yitzhak2026') is done
-- automatically by the app's init_db() when the users table is empty.
-- Change these passwords from the User Management page after first login.
