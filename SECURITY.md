# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability.

Send a private report to the maintainers with:

- affected version or commit
- a short description of the issue
- reproduction steps or a proof of concept
- the impact you believe it has

If the repository has GitHub private vulnerability reporting enabled, use **Security → Report a vulnerability** there.

You should receive an acknowledgement within 3 business days. Please give us time to ship a fix before public disclosure.

## Scope

In scope:

- authentication and authorization bypass
- cross-tenant or cross-team data exposure
- injection (SQL, command, template)
- webhook signature bypass
- secret leakage to logs, responses or the browser
- stored or reflected XSS

Out of scope:

- vulnerabilities in Meta / WhatsApp or in a third-party knowledge base
- issues that require an already-compromised server
- denial of service caused by unrealistic traffic without a concrete fix
- missing security headers on a development-only setup

## Hardening checklist for operators

- Set `APP_ENV=production` and a long random `APP_SECRET`.
- Set `DEMO_SEED=0` and create the first owner with `scripts/create_admin.py`.
- Put the app behind HTTPS and restrict `ALLOWED_ORIGINS`.
- Keep the SQLite file and backups outside the web root.
- Rotate WhatsApp and knowledge-base credentials on a schedule.
- Do not expose the app directly to the internet without a reverse proxy and rate limiting.
