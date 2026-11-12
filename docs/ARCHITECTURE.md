# Architecture

## Overview

DeskClerk AI Autopilot is a single-tenant web application with three external boundaries: the browser, WhatsApp Cloud API, and an optional knowledge-base API.

```text
┌──────────────┐       HTTPS / JSON        ┌──────────────────┐
│   Browser    │ ────────────────────────► │  FastAPI + JWT   │
│  vanilla JS  │ ◄──────────────────────── │  authorization   │
└──────────────┘                           └────────┬─────────┘
                                                     │
                              ┌──────────────────────┼──────────────────────┐
                              ▼                      ▼                      ▼
                       ┌────────────┐        ┌─────────────┐        ┌──────────────┐
                       │ SQLite WAL │        │ WhatsApp    │        │ Knowledge    │
                       │ app.db     │        │ Cloud API   │        │ base API     │
                       └────────────┘        └─────────────┘        └──────────────┘
```

## Components

| Component | Location | Responsibility |
|---|---|---|
| HTTP API | `app/main.py` | Routes, validation, authorization, webhook handling, AI orchestration |
| Data layer | `app/db.py` | Schema, migrations, seed data, settings |
| Auth | `app/auth.py` | PBKDF2 hashing, JWT issuance and verification |
| Web UI | `app/static/` | SPA, views, forms, client-side routing |
| Tests | `scripts/` | API, fuzz, edge, performance, UI and smoke suites |

## Request flow

1. The browser sends a JWT in the `Authorization` header.
2. `current_user` resolves the token and loads the active user.
3. The route applies role, data-scope, read-only and ownership checks.
4. The handler reads or writes SQLite through the data layer.
5. Mutating actions write an audit record.

The UI hides controls for convenience, but the server is the authority. A hidden button is not a permission.

## Inbound WhatsApp flow

```text
Meta webhook
   │  verify signature (when app secret is configured)
   ▼
find number by phone_number_id
   │
   ├── messages ──► find/create contact and conversation
   │                 ├── detect opt-out keywords
   │                 ├── store message with wa_message_id
   │                 └── start AI handling in a background thread
   │
   └── smb_message_echoes ──► store as outbound, via = app
```

The webhook returns quickly; AI work happens in a daemon thread so Meta does not retry because of model latency.

## Data model

Core tables:

- `users`, `teams`, `team_members`
- `numbers`, `number_teams`
- `contacts`, `contact_tags`, `tags`
- `segments`
- `templates`, `campaigns`, `campaign_recipients`
- `conversations`, `messages`
- `ai_logs`, `ai_drafts`
- `settings`, `audit`

SQLite runs in WAL mode with a busy timeout. The application keeps foreign-key-style cleanup in code rather than relying on the database engine.

## Trust boundaries

| Boundary | Trust |
|---|---|
| Browser | Untrusted input; every field is validated and escaped |
| WhatsApp webhook | Untrusted until the signature is verified |
| Knowledge-base response | Untrusted content; treated as data, not instructions |
| SQLite file | Trusted local state; must be protected by file permissions and backups |
| Environment variables | Trusted secrets; never sent to the browser |

## Deployment topology

A single process is the supported default:

```text
Internet → Caddy/Nginx (TLS) → Uvicorn → SQLite file
```

For multiple app processes, move rate limiting to a shared store and migrate to PostgreSQL first. The current in-process limiter and background threads assume one process.

## Failure behavior

- AI failure: hand off to a human; never send an empty or fabricated answer.
- Webhook duplication: ignored by `wa_message_id`.
- Database lock: bounded wait, then an error; no silent data loss.
- Missing WhatsApp credentials: messages remain local; nothing is sent.
- Missing `APP_SECRET` in production: startup fails loudly.
