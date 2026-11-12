# Contribution workflow

This document explains how an outside contributor gets a change into the repository. The short version: **open an issue, fork, branch, test, pull request, CI, review, merge, release.**

## 1. The flow

```text
Find or open an issue
        │
        ▼
Maintainer agrees on scope (large changes only)
        │
        ▼
Fork the repository
        │
        ▼
Create a branch
        │
        ▼
Change code + tests + docs
        │
        ▼
Run ./scripts/run_all_tests.sh --quick
        │
        ▼
Open a pull request
        │
        ├── CI: tests
        ├── CI: CodeQL
        └── Review by a maintainer
                │
                ├── changes requested ──► update the same branch
                └── approved
                        │
                        ▼
                     Merge
                        │
                        ▼
                 Release when ready
```

## 2. Before writing code

| Change type | What to do |
|---|---|
| Typo, docs, translation | Open a pull request directly |
| Small bug with reproduction | Open an issue, then a pull request |
| New feature or behavior change | Open an issue first and wait for scope agreement |
| Security vulnerability | Follow [SECURITY.md](../SECURITY.md), never a public issue |
| Large refactor or new dependency | Open an issue first; explain the trade-off |

This prevents a contributor from spending days on a change that does not fit the project.

## 3. Fork and branch

Fork the repository on GitHub, then:

```bash
git clone https://github.com/<your-account>/deskclerk-autopilot.git
cd deskclerk-autopilot
git remote add upstream https://github.com/jovian6661/deskclerk-autopilot.git
git checkout -b fix/pool-protection-period
```

Branch names:

| Prefix | Use |
|---|---|
| `feat/` | new capability |
| `fix/` | bug fix |
| `docs/` | documentation only |
| `test/` | test improvements |
| `refactor/` | behavior-preserving cleanup |
| `chore/` | tooling, CI, dependencies |

Keep the branch focused. One concern per pull request.

## 4. Make the change

- Read the relevant file in `docs/` before changing a rule.
- Add or update a test for behavior changes.
- Update the document that describes the rule, field, endpoint or permission.
- Do not commit secrets, customer data, database files, screenshots with personal data, or generated `data/`.
- AI-assisted contributions are welcome. You are responsible for correctness, licensing and testing.

## 5. Run the tests

Before opening the pull request:

```bash
./scripts/run_all_tests.sh --quick
```

Before a release, or when touching permissions, the pool, AI flows or the database layer:

```bash
./scripts/run_all_tests.sh --full
```

The suite starts its own servers and temporary databases. It does not touch `data/app.db`.

## 6. Open the pull request

Use the pull request template. Include:

- the problem;
- what changed;
- how you tested it;
- screenshots for UI changes;
- documentation updates;
- anything reviewers should know: migrations, behavior changes, follow-ups.

The CI runs automatically:

- `tests` — API, fuzz, edge/security/performance, UI and smoke;
- `CodeQL` — Python and JavaScript analysis.

A pull request is not merged while a required check is failing.

## 7. Review

A maintainer will review for:

- correctness and edge cases;
- permission and data-scope enforcement;
- backward compatibility;
- test coverage;
- documentation;
- security and secret handling.

Reviews are best-effort. A small, focused pull request with a clear test gets reviewed faster than a large one.

If changes are requested, push more commits to the same branch. Do not open a second pull request for the same change.

## 8. Merge

The maintainer merges after:

- CI is green;
- the change is reviewed;
- the documentation is updated;
- no secrets or customer data are included.

Squash merge is preferred for a clean history. The contributor remains credited in the commit or release notes.

## 9. Release

Maintainers follow [RELEASING.md](RELEASING.md):

- update `CHANGELOG.md`;
- bump the version under Semantic Versioning;
- tag `vX.Y.Z`;
- publish a GitHub Release;
- write migration notes if the database changed.

## 10. Labels

| Label | Meaning |
|---|---|
| `good first issue` | small, well-scoped, good entry point |
| `help wanted` | maintainers would welcome a contributor |
| `bug` | confirmed defect |
| `enhancement` | new capability or improvement |
| `documentation` | docs, examples, translations |
| `security` | security-sensitive; do not discuss details publicly |
| `needs triage` | not yet reviewed |
| `dependencies` | dependency update |
| `ci` | workflow or tooling |

## 11. Branch protection

`main` is protected on GitHub:

- changes go through a pull request;
- the `test` status check must pass;
- force pushes and branch deletion are blocked;
- maintainers can bypass in an emergency, but should not use that for normal work.

## 12. What maintainers do

- Triage issues and label them.
- Confirm scope before large work.
- Review pull requests and run the full suite before release.
- Keep `main` releasable.
- Protect secrets and customer data.
- Follow [GOVERNANCE.md](../GOVERNANCE.md).

## 13. What contributors should not do

- Do not push directly to `main`; use a pull request.
- Do not include real customer data or API keys.
- Do not add an unofficial WhatsApp gateway.
- Do not remove license, security or trademark notices.
- Do not use the DeskClerk name or logo as the branding of a fork.
