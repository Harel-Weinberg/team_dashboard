# 🚀 AI & Tech Innovation — Team Dashboard

Internal project management & control dashboard for a 2-person team (Harel & Yitzhak).
Built with **Streamlit** + **Supabase (cloud PostgreSQL)** so it syncs live across
multiple computers — no local files, no local database.

## Architecture

| File | Responsibility |
|---|---|
| `main.py` | Entry point: page config, auth gate, view routing |
| `auth.py` | DB-driven login/logout, stores user + role in `st.session_state` |
| `database.py` | All PostgreSQL access + automatic schema creation & migration |
| `ui_components.py` | Sidebar, project dashboard (Spec / Tasks / Chat), task boards |
| `admin_ui.py` | User Management page (admins only): add / rename / password / contacts / delete |
| `notifications.py` | Outbound notifications (email via SMTP, WhatsApp-ready) |
| `theme.py` | Global RTL (Hebrew) stylesheet + component styling |
| `optimistic.py` | Optimistic UI engine: instant echoes + background DB sync |
| `schema.sql` | Same schema, for manual setup in the Supabase SQL Editor (optional) |
| `.streamlit/secrets.toml` | DB connection credentials (**never commit**) |

Every write (project, spec, task, note, chat message) is automatically tagged
with the active user's name and a server-side timestamp (`NOW()` in Postgres),
displayed in Israel time.

## Setup (one time)

### 1. Create the Supabase database
1. Sign up at [supabase.com](https://supabase.com) (free tier is fine) and create a new project.
2. Go to **Project Settings → Database** and note the **Transaction pooler**
   connection parameters (host ends with `pooler.supabase.com`, port **6543**).
   The pooler is IPv4-friendly and handles connection pooling server-side,
   which is exactly what we want when two computers connect concurrently.
3. (Optional) Run `schema.sql` in the **SQL Editor** — otherwise the app
   creates all tables automatically on first run.

### 2. Configure secrets
Edit `.streamlit/secrets.toml` and fill in `[database]` — your Supabase pooler
host, user (`postgres.<project-ref>`) and password.

### User accounts (stored in the database, not in secrets)
Users live in the `users` table with SHA-256 hashed passwords and a role
(`admin` / `user`). On first run, if the table is empty, the app seeds two
default **admin** users so you can't get locked out:
`Harel / harel2026` and `Yitzhak / yitzhak2026` — **change these passwords
immediately** from the **👥 User Management** page (visible to admins in the
sidebar), which also lets you add users, change passwords, and delete users
(deleting yourself or the last admin is blocked).

### 3. Install & run (on each computer)
```bash
cd team_dashboard
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run main.py
```

Each teammate can run the app locally on their own machine — both instances
talk to the same cloud database, so everything stays in sync.

> **Alternative:** deploy once to [Streamlit Community Cloud](https://share.streamlit.io)
> (paste the contents of `secrets.toml` into the app's Secrets settings there)
> and both users simply open the same URL — no local install needed.

## Notifications

Two automatic triggers, sent by email (`notifications.py`):

| Trigger | Recipient | Message |
|---|---|---|
| A new **urgent** task is created | the assignee | היי {שם}, נוספה לך משימה דחופה: {משימה}. |
| A task moves from open to **completed** | the person who created it | היי, המשימה '{משימה}' בוצעה בהצלחה על ידי {שם}. |

Sending happens on a background thread, so the UI never waits on it; the user
sees an instant `st.toast`. Completing your own task doesn't notify you
(set `NOTIFY_SELF = True` in `notifications.py` to change that).

**Setup:** add each user's email in **👥 ניהול משתמשים → 📧 פרטי קשר**, then
add an `[smtp]` block to `.streamlit/secrets.toml` (see the commented example
there — Gmail needs an App Password). Until SMTP is configured, notifications
are only written to the console log, which is handy for local testing:

```
2026-08-17 14:55:33 [NOTIFY] INFO: to=Harel channel=email target=harel@... message=היי Harel, נוספה לך משימה דחופה: ...
```

WhatsApp via Twilio is stubbed out in `_send_whatsapp()` — install `twilio`,
set `NOTIFY_CHANNEL=whatsapp` and the `TWILIO_*` variables to switch channel.

## Usage notes

- **🔄 Refresh** (sidebar) pulls your teammate's latest changes; Streamlit also
  refreshes data on every interaction.
- **Spec editing is last-write-wins**: if both users edit the spec at the same
  moment, the later save overwrites the earlier one. Coordinate big edits via
  the project chat.
- **Urgent Tasks** and **Future Backlog** are global boards (not tied to a
  project) and support the same assignees, checkboxes and per-task notes.
