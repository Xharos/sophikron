# Sophikron backend

FastAPI, SQLAlchemy asyncio, psycopg and PostgreSQL. Application endpoints are registered through
`app/api/router.py` under `/api/v1`; `/health` is an unversioned infrastructure readiness check.

See [authentication](../docs/authentication.md) for identity encryption, key generation, initial
administrator setup, API contracts, SMTP, sessions and verification. See
[database operations](../docs/database.md) for database roles, secrets and Alembic.

See [administration](../docs/administration.md) for integer account IDs, generated immutable usernames,
four encrypted identity fields, explicit permissions, promotions, fuzzy name search and activity.
The shared responsive frontend uses these contracts; see [frontend and BFF](../docs/frontend-bff.md).
Complete school profiles keep optional private information encrypted in `users`, with administrator
editing and scoped teacher orientation editing; see [profile contracts](../docs/administration.md#complete-school-profiles).

Install into the configured Python environment with `python -m pip install -e ".[dev]"`. Run:

```sh
python -m pytest -q -m "not integration"
ruff check .
```

The complete `python -m pytest -q` suite includes real PostgreSQL tests only when explicitly enabled
against `sophikron_test`. Tests never substitute SQLite for PostgreSQL constraints or concurrency.

## PyCharm Run / Debug

Use the single Python configuration **run_tests**, targeting `backend/run_tests.py` with the local
interpreter of the `sophikron-api` module and working directory `backend/`. Its persistent local
configuration is in `.idea/runConfigurations/run_tests.xml` (IDE settings are excluded from Git).
The same entry point is available from the terminal with `python run_tests.py` in `backend/`.

With Docker Desktop running, click Run or Debug. The launcher creates synthetic secrets in a private
temporary directory and a unique `sophikron-tests-<random>` Compose project. It reuses `compose.yaml`
without reading `.env`, builds/starts PostgreSQL and the API, waits for migrations and health, then
runs **all** backend tests locally, including PostgreSQL integration tests. Docker assigns free
loopback-only ports; no fixed ports or local secrets need configuring.

The launcher removes its containers, networks, volumes and project image tags in a `finally` block,
including after test/startup failures and normal interruption. It then removes its temporary secrets.
Development containers, volumes and secrets are never selected. Docker build cache may remain for
faster subsequent runs. If Docker becomes unavailable or the process is forcibly killed, cleanup
cannot be guaranteed: the console prints the exact disposable project name for manual recovery.

Pytest runs in the Python configuration's process, so Debug supports breakpoints in tests and API
services called through ASGI. The output is a pytest console summary rather than the IDE's pytest
tree. The live API process remains in Docker; debugging that process requires a separate setup.
The first run may take longer while Docker builds images. By default only backend services/tests run.
Set `BFF_INTEGRATION=1` for the real HTTP frontend journey, and additionally
`BFF_BROWSER_INTEGRATION=1` for Playwright desktop/mobile interactions using installed Edge
(`BFF_BROWSER_CHANNEL` can select another installed Playwright channel).

Normal local startup uses `docker compose up -d --build` from the repository root. Compose runs the
migration service before the API. A fresh installation requires `AUTH_BOOTSTRAP_USERNAME` and a
mounted bootstrap password; complete it through `POST /api/v1/auth/setup`. The
installation secret is separate from permanent passwords: it may be simple or empty. New permanent
passwords require 10–128 ASCII characters with lowercase, uppercase, digits and punctuation.
Login failure budgets are configurable through `AUTH_LOGIN_IP_LIMIT` (20),
`AUTH_LOGIN_IDENTITY_LIMIT` (5 per IP/identifier) and `AUTH_RATE_WINDOW_SECONDS` (900).
Successful logins do not consume or reset these budgets. Authentication/admin bodies are capped at
16 KiB before JSON parsing, and password-worker queues are bounded. See the authentication guide
for overload responses and baseline schema compatibility. Swagger documents the
`X-CSRF-Protection` header (enter `1` on writes), and uses the browser cookie automatically.
