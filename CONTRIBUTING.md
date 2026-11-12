# Contributing

Thanks for taking the time to contribute.

The full flow — issue, fork, branch, tests, pull request, CI, review, merge and release — is in [docs/CONTRIBUTING-WORKFLOW.md](docs/CONTRIBUTING-WORKFLOW.md). Release mechanics are in [docs/RELEASING.md](docs/RELEASING.md).

## Before you start

- For a bug, open an issue with the version, steps to reproduce and what you expected.
- For a security problem, follow `SECURITY.md` — do not open a public issue.
- For a large feature, open an issue first so we can agree on scope before you write code.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

export APP_SECRET=dev-secret
./run.sh
```

No frontend build step is required. Edit files in `app/static/` and refresh the browser.

## Tests

Run the quick suite before every pull request:

```bash
./scripts/run_all_tests.sh --quick
```

Run the full suite before a release or when touching permissions, the pool, AI flows or the database layer:

```bash
./scripts/run_all_tests.sh --full
```

The tests create their own temporary databases and servers. They do not touch `data/app.db`.

## Code style

- Keep the backend dependency-light. Do not add a framework or an ORM without discussing it first.
- Keep the frontend build-free: no bundler, no CDN, no UI framework.
- Comments should explain *why*, not *what*. Most code should need no comment.
- New endpoints must enforce role, data scope and read-only rules in the backend. Hiding a button is not authorization.
- Never commit credentials, real customer data, API keys, database files or screenshots containing personal data.

## Pull requests

- Keep the change focused. One concern per pull request.
- Describe the problem, the approach and how you tested it.
- Include a test for behavior changes when practical.
- Update the relevant file in `docs/` when a rule, field, endpoint or permission changes.
- Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- For larger changes, read [GOVERNANCE.md](GOVERNANCE.md) and open an issue first.

## Commit messages

Use a short imperative subject line, then explain the why in the body when it is not obvious. Do not include secrets, customer data or generated databases.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0. Brand use is governed by [TRADEMARK.md](TRADEMARK.md).
