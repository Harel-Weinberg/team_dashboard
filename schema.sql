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

-- Default admin seeding (dummy passwords 'harel2026' / 'yitzhak2026') is done
-- automatically by the app's init_db() when the users table is empty.
-- Change these passwords from the User Management page after first login.
