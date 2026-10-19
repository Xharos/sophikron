# PostgreSQL infrastructure

The backend uses SQLAlchemy 2.x asynchronous engines and sessions with psycopg 3. Alembic owns
application schema migrations. PostgreSQL 17 is the local reference database.

## Local Docker Compose setup

Docker Desktop must use Linux containers. No local Python installation is needed to run the stack.
Compose reads the local `.env` file. It is excluded from Git and Docker build contexts. The default
connection settings are also defined in `compose.yaml`, so a fresh checkout works without an `.env`.
Use `DB_NAME` to select the database and `DB_ADMIN_SECRET_PATH`, `DB_APP_SECRET_PATH` and
`DB_MIGRATION_SECRET_PATH` to select the three secret files (defaults: `./secrets/db_admin_password`,
`./secrets/db_app_password`, `./secrets/db_migration_password`). The old local `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD` settings are unused; Compose defines the container's
PostgreSQL settings explicitly. Passwords belong in secret files, not `.env`.

Provide three independent password files at the paths selected in `.env`. The local setup may keep
them outside the project on a drive accessible to Docker Desktop. These files are local configuration,
not generated build artifacts, and must be preserved between starts. Restrict access using Windows
filesystem permissions; never commit them. Secret values must be UTF-8, nonempty and single-line;
the application accepts an optional trailing line ending. Changing a file does not change an existing
PostgreSQL role's password; coordinate password changes with PostgreSQL and restart the backend.

If Docker Desktop cannot mount files on the project drive, place the files in an accessible local
directory and set these paths in `.env`, for example:

```dotenv
DB_ADMIN_SECRET_PATH=C:/secure/sophikron/db_admin_password
DB_APP_SECRET_PATH=C:/secure/sophikron/db_app_password
DB_MIGRATION_SECRET_PATH=C:/secure/sophikron/db_migration_password
```

Choose a directory you own and protect it with appropriate ACLs. The settings above contain
only paths. On Linux, keep the source directory restricted (for example mode `0700`), while making
individual secret files readable by the container's runtime UID `10001`. File-backed Compose secrets
preserve host permission constraints; their `uid`, `gid` and `mode` settings are not a portable way to
fix source-file permissions. A readable file inside a restricted parent directory is one option.

Start a new, uninitialized database, explicitly migrate it, then start the application:

```sh
docker compose up -d --build --wait db
docker compose run --build --rm migrate
docker compose up -d --build backend frontend
```

The API is available at `http://localhost:8000`, the frontend at `http://localhost:3000`. PostgreSQL
is published only on `127.0.0.1:5432` for local Python tests and database tools. `DB_PUBLISHED_PORT`
changes that host port; `BACKEND_PORT` changes the API's host port. Inside Docker, PostgreSQL still
uses port 5432. `GET /` is independent of PostgreSQL. `GET /health` checks connectivity
within `DB_HEALTH_TIMEOUT`, returns 503 without connection details on failure, and can recover without
an API restart. Startup validates configuration and secret access but does not require a connection.
The health check tests connectivity, not migration currency; deployments must run Alembic explicitly.

**Existing volumes:** initialization scripts only run when PostgreSQL's data directory is empty.
An old volume retains its database name, administrator and passwords. Even a volume with no business
rows can already be initialized. This change does not delete it, change its ownership or apply role
provisioning to it. Before reusing an existing volume, inspect its state and prepare a reviewed
provisioning procedure with its current administrator. Do not delete or reset it without explicit
authorization. Using a separate Compose project creates an independent local volume if desired.

## Roles and runtime secrets

| Role | Purpose | Secret available to |
| --- | --- | --- |
| `postgres` | Initial provisioning and cluster administration | PostgreSQL container |
| `sophikron_migrator` | Owns the `sophikron` schema and creates/updates its objects | PostgreSQL initialization and explicit migration service |
| `sophikron_app` | Application data access, without schema or role administration | PostgreSQL initialization and backend |

The runtime and migration roles are neither superusers nor database/role creators. The application
cannot assume the migration role. Public database/schema privileges are revoked. Default privileges
grant application DML on future migration-owned tables and sequence usage; public execution of future
migration-owned functions is revoked. Alembic explicitly revokes application access to its version
table in the migration transaction. Restrict grants further when future business models require it.
Database roles do not replace application authentication or authorization between users.

The database image extends the official `postgres:17` image with reviewed initialization SQL.
Authentication over the Docker network uses SCRAM-SHA-256. Compose secrets are mounted files under
`/run/secrets`; local Compose does not encrypt their source files. The backend only loads its own
password, once at startup. There is no password or complete connection URL in the Compose environment,
image or source configuration. An administrator controlling Docker or the host can access mounted
secrets. Restrict Docker access and protect the host.

## Configuration

`DatabaseSettings` reads environment variables only; it does not automatically load `.env`. These
settings apply to processes inside containers. `DB_*_SECRET_PATH` in `.env` are host paths
used by Compose, not application settings.

| Variable | Default / requirement |
| --- | --- |
| `DB_HOST` | Required; `db` in Compose; libpq multi-host lists can be supplied here |
| `DB_PORT` | `5432`; shared port for hosts in the list |
| `DB_NAME` | Required; `sophikron` in Compose |
| `DB_USER` | Required; application or migration role |
| `DB_PASSWORD_FILE` | Required; readable runtime secret file |
| `DB_POOL_SIZE` | `5`, at least 1 |
| `DB_MAX_OVERFLOW` | `5`, bounded and never unlimited |
| `DB_POOL_TIMEOUT` | `5` seconds waiting for a pooled connection |
| `DB_POOL_RECYCLE` | `1800` seconds; checked when acquiring connections |
| `DB_CONNECT_TIMEOUT` | `5` seconds per host connection attempt; minimum 2 |
| `DB_STATEMENT_TIMEOUT_MS` | `10000`; migration service uses `60000` |
| `DB_LOCK_TIMEOUT_MS` | `2000` |
| `DB_IDLE_TRANSACTION_TIMEOUT_MS` | `30000` |
| `DB_HEALTH_TIMEOUT` | `2` seconds for the entire readiness operation |
| `DB_SSLMODE` | `disable` for the local Docker network |
| `DB_SSLROOTCERT` | Optional CA certificate file path |
| `DB_TARGET_SESSION_ATTRS` | `read-write`; also accepts `primary` or `any` |

Size the connection budget for all processes and replicas: each application process can use up to
`DB_POOL_SIZE + DB_MAX_OVERFLOW` connections, plus migration and administration connections.
SQLAlchemy owns the only application pool. `pool_pre_ping` replaces stale connections on checkout;
it cannot save an interrupted transaction. Recycling does not interrupt active transactions.
Server-side statement/lock/idle timeouts and pool/connection timeouts address different waits.
Other endpoints may need their own overall request deadlines as they are introduced.

`URL.create` handles password characters without manual URL interpolation. SQL values must be bound
parameters; never build SQL from user input with string concatenation or f-strings. Dynamic identifiers
require trusted SQLAlchemy objects or explicit allowlists. SQLAlchemy hides bound parameters in its
errors, but callers must still avoid logging raw exceptions, complete URLs, secrets or personal data.
PostgreSQL server logs also require their own privacy review.

## Sessions and transactions

The application lifespan owns one `Database` resource per process and disposes it at shutdown. Each
`get_db` dependency yields a fresh `AsyncSession`, closes it on completion/error/cancellation and
never commits implicitly. Use a separate session per concurrent task. Services define the transaction
before performing database operations:

```python
async with session.begin():
    await session.execute(statement, parameters)
```

The context commits on success and rolls back on exceptions. If a read has already started a
transaction through SQLAlchemy's autobegin, finish it before opening a new explicit transaction.
Data-access helpers should not independently commit parts of a larger business operation. Do not
hold transactions open during unrelated network calls. `expire_on_commit=False` avoids implicit
reload after a commit; load relationships explicitly in asynchronous code.

No automatic write retry is performed. Following a disconnect during commit, its result may be
unknown. Future retry policies must consider idempotency and retry the complete transaction only
where its business semantics allow it.

## Migrations

Add future model imports in `app/models/__init__.py` so Alembic sees them through `Base.metadata`.
Metadata uses the explicit `sophikron` schema and stable constraint names. Name check constraints.
Connections use `search_path=pg_catalog`; qualify application tables explicitly in handwritten SQL.
Alembic inspects only the application schema and uses a dedicated connection with `NullPool`.
Its baseline records revision tracking without introducing business tables.

The migration service defaults to `alembic upgrade head`. Supply a full command to override it:

```sh
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic check
docker compose run --rm migrate alembic upgrade head
```

For authoring migration files, run Alembic from `backend/` with the
migration role's settings and secret file. Container-generated files otherwise disappear when the
one-off container is removed. Review generated SQL and never modify an already-applied revision.
Run migrations once as a controlled deployment step, not from every API worker. Ensure the secret
remains readable even when rendering offline SQL; no URL with credentials is written to `alembic.ini`.

## Verification

From `backend/`, after installing development dependencies in the configured Python environment:

```sh
python -m pytest -q
ruff check .
```

Run only the fast tests with `python -m pytest -q -m "not integration"`. These tests check
configuration validation, secret redaction, HTTP error handling, real session closure without
database access, and engine disposal at application shutdown. The integration tests exercise the
actual request session dependency for isolation, rollback and task cancellation.

Compose contains only `db`, `backend`, `frontend` and `migrate`. There is no test profile or test image.
Pytest runs in the configured local Python environment against the full PostgreSQL and API services.
Install the backend's development dependencies locally; they are not included in the runtime image.

Integration tests are skipped without `DB_INTEGRATION=1`. Use a dedicated database named
`sophikron_test`, not the development database: the migration tests downgrade and reapply revisions.
The following PowerShell example uses the normal services in a separate Compose project, with
different host ports so the development application can remain running. Run it in a separate terminal
at the project root so these process-local environment overrides do not affect normal development:

```powershell
$env:DB_NAME = 'sophikron_test'
$env:DB_PUBLISHED_PORT = '55432'
$env:BACKEND_PORT = '18000'
docker compose -p sophikron-tests up -d --build --wait db backend
docker compose -p sophikron-tests run --build --rm migrate

$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '55432'
$env:DB_USER = 'sophikron_app'
$env:DB_PASSWORD_FILE = (Resolve-Path ./secrets/db_app_password).Path
$env:DB_TEST_MIGRATION_PASSWORD_FILE = (Resolve-Path ./secrets/db_migration_password).Path
$env:DB_TEST_API_URL = 'http://127.0.0.1:18000'
$env:DB_INTEGRATION = '1'
Set-Location backend
python -m pytest -q
Set-Location ..
docker compose -p sophikron-tests down
```

Adapt the two local password paths if you placed secrets outside the project. Compose reads its host
secret paths from `.env` or `DB_*_SECRET_PATH` environment overrides; pytest reads the same files via
`DB_PASSWORD_FILE` and `DB_TEST_MIGRATION_PASSWORD_FILE`. Use dedicated test secrets when possible.
The separate project uses its own named database volume; `down` preserves it for subsequent runs.
Do not delete volumes without explicit authorization. Closing this terminal discards the environment
overrides. No additional Compose services or test-only Docker build stages are needed.

The runtime image runs as UID `10001`; tests exercise its HTTP endpoints and mounted secret. Tests
also cover migrations, role boundaries, commit/rollback, cancellation, independent sessions, bound
SQL values, pool saturation, disconnected idle connections, statement timeouts and lock contention.
The suite refuses database names other than `sophikron_test` before running migration or database
tests. Never point it at a valuable database. CI starts the same full services and runs pytest from
its Python environment against its dedicated test database.

The live HTTP checks validate status codes and JSON responses; they do not audit container users or
secret mount permissions. The migration round trip currently smoke-tests the baseline and Alembic
wiring; future business migrations need their own data-preservation checks. On migration command
failure, captured diagnostics are reported with the known database passwords redacted.

Validate configuration without displaying any resolved values:

```sh
docker compose config --quiet
```

## Production and future encryption

The Compose configuration is for local development. For remote PostgreSQL, configure TLS certificate
verification (`DB_SSLMODE=verify-full`, trusted CA and matching hostname) and mount the CA certificate.
Multi-host connection selection can support a future primary endpoint, but does not configure
replication or failover orchestration. A future PgBouncer deployment needs its own pooling and
prepared-statement compatibility review.

User and associated personal data are intended to be encrypted in the application before storage;
pedagogical resources are outside that future encryption scope. This change does not implement
encryption of business data. Choose protected fields, searchable representations, key storage,
rotation and restoration before introducing real personal data. Keep encryption keys separate from
PostgreSQL and its backups. Passwords for user accounts must use password hashing, not reversible
encryption. Storage encryption and encrypted backups remain separate deployment responsibilities.
