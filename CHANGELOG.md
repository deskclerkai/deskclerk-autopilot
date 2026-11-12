# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-11-12

### Added

- WhatsApp shared inbox across multiple company numbers.
- Contact profiles, tags, deal stages, ownership and CSV export.
- Custom segments with rule-based matching.
- Public pool with opt-out, success-state, protection-period, tag-scope and quota rules.
- Campaigns with consent checks and approved-template requirements.
- Owner, manager and agent roles; team-scoped data and read-only seats.
- WhatsApp Cloud API webhook, message de-duplication and coexistence echo handling.
- AI reception in manual, draft and autopilot modes, with safety boundaries, citations and handoff.
- AI customer insights on the contact card.
- Twelve analytics boards with nine filter dimensions.
- Audit log, number management and WABA sync.
- Docker and local deployment.
- API, fuzz, edge, performance and Playwright test suites.

### Security

- PBKDF2 password hashing and JWT expiry.
- Server-side authorization for writes, replies and read-only seats.
- Webhook signature verification when an app secret is configured.
- Production startup guard for `APP_SECRET`.
- No telemetry sent to the maintainers.

[Unreleased]: https://github.com/jovian6661/deskclerk-autopilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jovian6661/deskclerk-autopilot/releases/tag/v0.1.0
