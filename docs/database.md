# PostgreSQL infrastructure

The backend uses SQLAlchemy 2.x asynchronous engines and sessions with psycopg 3. Alembic owns
application schema migrations. PostgreSQL 17 is the local reference database.

## Local Docker Compose setup

Docker Desktop must use Linux containers. No local Python installation is needed to run the stack.
Compose reads the single private `.env` file. It is excluded from Git and Docker build contexts.
`compose.yaml` is the only Compose configuration, shared by development and isolated verification.
Backend pool, timeout and authentication values are configured in `.env`; Compose lists the allowed
variables and keeps container wiring and secret mounts explicit. Examples for `.env` are in
[authentication configuration](authentication.md#keys-and-configuration).
Use `DB_NAME` to select the database and `SOPHIKRON_SECRETS_DIRECTORY` to select the directory
containing all six secret files. PostgreSQL uses `db_admin_password`, `db_app_password` and
`db_migration_password` directly in that directory. The old local `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD` settings are unused; Compose defines the container's
PostgreSQL settings explicitly. Passwords belong in secret files, not `.env`.

Provide three independent password files in the directory selected in `.env`. The local setup may keep
them outside the project on a drive accessible to Docker Desktop. These files are local configuration,
not generated build artifacts, and must be preserved between starts. Restrict access using Windows
filesystem permissions; never commit them. Secret values must be UTF-8, nonempty and single-line;
the application accepts an optional trailing line ending. Changing a file does not change an existing
PostgreSQL role's password; coordinate password changes with PostgreSQL and restart the backend.

If Docker Desktop cannot mount files on the project drive, place the files in an accessible local
directory and set its path in `.env`, for example:

```dotenv
SOPHIKRON_SECRETS_DIRECTORY=C:/Users/burga/AppData/Local/Sophikron
```

Choose a directory you own and protect it with appropriate ACLs. The settings above contain
only paths. On Linux, keep the source directory restricted (for example mode `0700`), while making
individual secret files readable by the container's runtime UID `10001`. File-backed Compose secrets
preserve host permission constraints; their `uid`, `gid` and `mode` settings are not a portable way to
fix source-file permissions. A readable file inside a restricted parent directory is one option.

Generate the identity keyring as described in [authentication](authentication.md), provide its
`identity_keys.json` file in the same directory, then start the application:

```sh
docker compose up -d --build
```

The API is available at `http://localhost:8000`, the frontend at `http://localhost:3000`. PostgreSQL
is published only on `127.0.0.1:5432` for local Python tests and database tools. `DB_PUBLISHED_PORT`
changes that host port; `BACKEND_PORT` changes the API's host port. Inside Docker, PostgreSQL still
uses port 5432. `GET /api/v1` is independent of PostgreSQL. `GET /health` checks connectivity
within `DB_HEALTH_TIMEOUT`, returns 503 without connection details on failure, and can recover without
an API restart. Startup validates secrets and reads the migrated installation-state row from PostgreSQL.
The health check tests connectivity; Compose runs Alembic automatically before API startup.
Direct non-Compose deployments must apply migrations explicitly. API startup now requires the
migrated installation-state row and database access.

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
settings apply to processes inside containers. `SOPHIKRON_SECRETS_DIRECTORY` is a host directory
used by Compose, not an application setting. Individual host secret-path overrides are not used.

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
Its consolidated initial revision creates authentication tables and the application role catalogue.
See [authentication migration compatibility](authentication.md#initial-consolidated-alembic-revision)
before using a database stamped with the previously empty baseline.

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

For a complete automatic local run, use **run_tests** in PyCharm or run `python run_tests.py` from
`backend/` using the configured interpreter. Docker Desktop must already be running. The launcher
creates a unique disposable Compose project, synthetic credentials and dynamically assigned local
ports, then runs the whole suite in the local interpreter. Its cleanup removes test volumes after
success, failure or normal interruption. It never loads the development `.env` or its secrets.
See [PyCharm Run / Debug](../backend/README.md#pycharm-run--debug) for the launch configuration.

The commands below remain available for running subsets or managing test services manually.

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

The session fixture removes the disposable live API bootstrap before isolated account scenarios.
Never use that database for manual accounts you want to preserve.

Integration tests are skipped without `DB_INTEGRATION=1`. Use a dedicated database named
`sophikron_test`, not the development database: the migration tests downgrade and reapply revisions.
The following PowerShell example uses the normal services in a separate Compose project, with
different host ports so the development application can remain running. Run it in a separate terminal
at the project root so these process-local environment overrides do not affect normal development:

```powershell
$env:DB_NAME = 'sophikron_test'
$env:DB_PUBLISHED_PORT = '55432'
$env:BACKEND_PORT = '18000'
$env:AUTH_BOOTSTRAP_USERNAME = 'verification_setup'
docker compose -p sophikron-tests up -d --build --wait db backend

$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '55432'
$env:DB_USER = 'sophikron_app'
$secretsDirectory = 'C:/Users/burga/AppData/Local/Sophikron'
$env:DB_PASSWORD_FILE = Join-Path $secretsDirectory 'db_app_password'
$env:DB_TEST_MIGRATION_PASSWORD_FILE = Join-Path $secretsDirectory 'db_migration_password'
$env:DB_TEST_API_URL = 'http://127.0.0.1:18000'
$env:DB_INTEGRATION = '1'
Set-Location backend
python -m pytest -q
Set-Location ..
docker compose -p sophikron-tests down
```

Adapt `$secretsDirectory` to the directory configured in `.env`. Compose reads the host directory
from `.env` or a `SOPHIKRON_SECRETS_DIRECTORY` environment override; pytest reads the same files via
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
secret mount permissions. The migration round trip checks the authentication schema and Alembic
wiring; old-baseline adoption checks preservation of unrelated stored data. On migration command
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

Usernames and emails in `users` are encrypted in the application before storage. Keyed lookup
indexes support exact search and uniqueness. Pedagogical resources, UUID relationships, roles and
security/statistics timestamps remain outside this field-encryption scope. See
[authentication](authentication.md) for keys, rotation, restoration, sessions and bootstrap. Keep
encryption keys separate from PostgreSQL and its backups. Account passwords use Argon2id hashing,
not reversible encryption. Storage encryption and encrypted backups remain deployment responsibilities.
