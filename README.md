# DeskClerk AI Autopilot

**Open-source WhatsApp operations desk for teams. Self-host the workflow. Plug in a knowledge base for the brain.**

A single-tenant, deployable WhatsApp customer-operations system: shared inbox, contact pool, public pool, ownership and permissions, campaigns, and AI-assisted replies through the official WhatsApp Cloud API.

> This project is an independent client. It is not affiliated with or endorsed by WhatsApp or Meta.

## Why this exists

Most WhatsApp "CRMs" either lock customer data inside a personal phone, or send through unofficial gateways that put the business number at risk. This project takes a different route:

- The WhatsApp number belongs to the company, not to an employee.
- Staff log in to the web desk; they never need the WhatsApp app on a personal phone.
- Customer ownership is a field in the database, so handovers, teams and a public pool actually work.
- Messaging uses the official Cloud API (or a coexistence setup), not an unofficial gateway.
- AI is optional and can draft, auto-reply, or stay off — per workspace and per conversation.

## Features

| Area | What it does |
|---|---|
| Inbox | Multi-number conversations, filters, assignment, 24-hour service window, contact side panel with recent messages |
| Contacts | Profiles, tags, deal stage, owner, opt-in/opt-out, CSV export, search and pagination |
| Segments | Four built-in lifecycle segments plus custom rule-based segments (tags, country, source, stage, consent, ownership, last contact) |
| Public pool | Unassigned contacts; claim rules include opt-out, won deals, protection period, tag scope and daily quota |
| Campaigns | Segment + approved template; only opted-in contacts are eligible |
| Templates | Local template library with review status; approval still happens in Meta |
| Teams & permissions | Owner / manager / agent, team-scoped data, field-level deal value, optional read-only seats, owner-only replies |
| Numbers | Multiple business numbers, WABA sync, quality and limits, team-level access |
| AI reception | Manual / AI draft / AI autopilot; per-language personas; safety boundaries; knowledge-base citations; handoff |
| AI insights | Auto tags, summaries, next action, risk flags on the contact card |
| Analytics | 9 filter dimensions and 12 boards: funnel, source, segments, country, tag, owner, team, number, stage, campaigns, AI quality |
| Audit | Login, assignment, claim, release, settings and AI changes |

## Architecture

```
Browser (vanilla JS SPA)
        │  JSON + JWT
        ▼
FastAPI  ──►  SQLite (WAL)
        │
        ├──► WhatsApp Cloud API webhook / send
        └──► Knowledge base API (DeskClerk by default)
```

- Python 3.9+, FastAPI, Uvicorn, PyJWT, requests
- SQLite with foreign-key-style application logic, no ORM
- No frontend build step, no CDN, no third-party UI framework
- Single process by default; put a reverse proxy (Caddy / Nginx) in front for HTTPS

## Quickstart (local)

```bash
git clone https://github.com/jovian6661/deskclerk-autopilot.git
cd deskclerk-autopilot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export APP_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
./run.sh
```

Open `http://127.0.0.1:8000`.

The first launch seeds a demo workspace so every page is usable:

```
owner@demo.com    / demo1234
manager@demo.com  / demo1234
agent@demo.com    / demo1234
```

**Never use the demo seed in production.** See below.

## Production install

```bash
export APP_ENV=production
export APP_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
export DEMO_SEED=0
export DB_PATH=/var/lib/deskclerk/app.db
export ALLOWED_ORIGINS=https://desk.example.com

python3 scripts/create_admin.py you@company.com 'a-long-password' 'Your Name'
./run.sh
```

`APP_ENV=production` refuses to start without `APP_SECRET`. `DEMO_SEED=0` creates an empty database and no demo accounts.

## Docker

```bash
cp .env.example .env
# edit .env: set APP_SECRET and APP_ENV=production
docker compose up -d --build

docker compose exec app python /app/scripts/create_admin.py you@company.com 'a-long-password' 'Your Name'
```

The SQLite database lives in `./data` on the host. Back it up before upgrades.

## Connect WhatsApp Cloud API

1. Create a Meta app with the WhatsApp product and a business number.
2. In **Settings → Integrations**, fill in the WABA ID, Phone Number ID, access token and app secret.
3. Set the webhook callback URL to `https://your-host/webhook/whatsapp` and subscribe to `messages`.
4. Set the same verify token in the app and in Meta.
5. Send a test message from a real phone; it should appear in the inbox within a few seconds.

Inbound messages are de-duplicated by `wa_message_id`. Webhook signature verification uses the app secret. Outbound sending is disabled until credentials are present, so a fresh install cannot accidentally message anyone.

The app also has a documented coexistence path for businesses that need the WhatsApp Business App and the API at the same time. See `docs/共存接入方案.md`.

## AI knowledge base

AI is provider-agnostic at the workflow level, with first-class support for the DeskClerk AI knowledge base:

1. Create a site and an integration key in DeskClerk AI.
2. Open **Settings → AI customer insights** (or the AI assistant page) and fill in base URL, site ID and key.
3. Choose a reception mode:
   - **Manual** — AI stays out of the way.
   - **AI draft** — drafts wait for a human to accept.
   - **AI autopilot** — confident, sourced answers are sent automatically; everything else is handed off.
4. Run the built-in test question and check the sources and latency.

Keys are stored server-side and masked in the UI. They are never written to logs or shipped to the browser. You can also supply the key through `AICHAT_KEY` instead of the database.

If you use another knowledge base, point the base URL and site credentials at it. The integration contract is documented in `docs/AI知识库接入.md`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET` | dev fallback in development | JWT signing key; required in production |
| `APP_ENV` | `dev` | Set `production` to enforce the secret check |
| `DB_PATH` | `data/app.db` | SQLite file |
| `DEMO_SEED` | `1` | `0` disables demo data and demo accounts |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins; restrict in production |
| `AICHAT_KEY` | empty | Knowledge-base key supplied by environment |
| `WA_APP_SECRET` | empty | WhatsApp app secret fallback |
| `PORT` | `8000` | Port used by `run.sh` |

## Tests

```bash
./scripts/run_all_tests.sh --quick   # API + smoke, under a minute
./scripts/run_all_tests.sh --full    # API, fuzz, edge/security/performance, UI, smoke
```

The suite starts its own servers and temporary databases. It covers permissions, pool rules, AI flows, fuzzing, JWT tampering, SQL injection, XSS payloads, database integrity, 2,000-contact performance and browser flows.

## Security notes

- Passwords use PBKDF2 with per-user salts; JWTs expire after 12 hours.
- Read-only seats are blocked from every write endpoint, not just hidden in the UI.
- Reply permission is enforced server-side: only the conversation owner can send.
- Inbound webhooks are signature-checked when an app secret is configured.
- Rate limiting is in-process. For multiple instances, put a shared limiter in front.
- SQLite is a good fit for a single team; move to Postgres before running many concurrent writers.

See `SECURITY.md` for reporting vulnerabilities.

## Known limitations

- Single-tenant: one deployment serves one company.
- SQLite, in-process rate limiting and in-process background threads assume one app process.
- Template approval still happens in Meta; the local status is a mirror.
- AI latency depends on the external knowledge base.
- The UI ships in English and Chinese; AI persona content can be written in any language.

## Contributing

Issues and pull requests are welcome. Read `CONTRIBUTING.md` first. For anything security-sensitive, follow `SECURITY.md` instead of opening a public issue.

## License and trademark

Code is licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`.

The DeskClerk name, the DeskClerk AI name and the DeskClerk logo are trademarks of the project owner. The code license does not grant permission to use them as the branding of a derivative product.
