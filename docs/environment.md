# Environment configuration reference

This document describes the configuration contract between the root `.env`, Docker Compose and
application processes. The public [`.env.example`](../.env.example) is the configuration template;
it contains examples and defaults, never installation secrets. Keep the private `.env` out of Git.

## How configuration is read

- Compose reads the root `.env` for `${...}` substitutions. Exported shell variables take precedence.
- Compose forwards only the settings explicitly listed in each service's `environment` section.
  Adding a variable to `.env` does not automatically pass it into a container.
- Native Python processes read their process environment, not `.env`. See the advanced settings in
  [authentication](authentication.md#keys-and-configuration) and [database configuration](database.md).
- An empty `NAME=` is an assigned empty value; `# NAME=value` is a comment. For Compose expressions
  using `${NAME:-default}`, both missing and empty values select the default. Preserve quoting when
  editing paths or values containing spaces, `#` or `$`.
- Use `docker compose -f compose.yaml -f compose.local.yaml config --quiet` to validate local wiring.
  Avoid printing the full resolved configuration in support logs; it can contain private settings.

For a new installation, copy `.env.example` to `.env`, choose the secret directory and create the
files below. For an existing installation, preserve current values and secrets. When aligning an
older `.env` with the template, absent settings can remain commented to retain Compose defaults.

## Application origin and ports

| Variable | Template/default | Purpose and what to enter |
| --- | --- | --- |
| `SOPHIKRON_ORIGIN` | Empty | Local overlay: empty selects `http://localhost:<FRONTEND_PORT>`. Production: exact public HTTPS origin such as `https://school.example.org`, without a trailing slash, path or query. |
| `FRONTEND_PORT` | `3000` | Host port for the frontend, bound to `127.0.0.1`. Choose an unused port from 1–65535. Changing it also changes the default local origin. |
| `BACKEND_PORT` | `8000` | Local overlay only: host API port on `127.0.0.1`. Production does not publish the API port. |
| `DB_PUBLISHED_PORT` | `5432` | Local overlay only: host PostgreSQL port on `127.0.0.1`. Production does not publish PostgreSQL. |

Use the same hostname in the browser throughout login and setup: `localhost` and `127.0.0.1` are
different origins. The documented local URL is `http://localhost:3000/login`. Port changes affect
host publication; the containers still communicate on their fixed internal ports.

## Secret directory and installation identity

| Variable | Template/default | Purpose and what to enter |
| --- | --- | --- |
| `SOPHIKRON_SECRETS_DIRECTORY` | `/absolute/path/to/private/sophikron` | Replace this placeholder with a real absolute host directory outside the repository. Use forward slashes on Windows, for example `C:/Users/yourname/AppData/Local/Sophikron`. Do not use `~`. |
| `AUTH_BOOTSTRAP_USERNAME` | `setup_operator` | Username of the temporary installation administrator. Use it with the `bootstrap_password` file for first login and complete `/setup`. It does not rename the permanent administrator or reopen completed setup. |

The directory must contain all six files, even when SMTP is disabled:

| File | What to put in it | Creation and lifecycle |
| --- | --- | --- |
| `db_admin_password` | Independent random PostgreSQL administrator password | Generate once; used for cluster initialization. |
| `db_app_password` | Independent random application SQL password | Generate once; the backend receives this credential, not administrator privileges. |
| `db_migration_password` | Independent random migration SQL password | Generate once; available to the migration service and initial SQL provisioning. |
| `bootstrap_password` | Independent random installation password | Generate once and read privately for setup. The temporary account is retired after setup. |
| `smtp_password` | SMTP provider password, or an empty file | Keep empty when mail is disabled or the SMTP server does not require authentication. |
| `identity_keys.json` | Versioned encryption and lookup keyring | Generate with the existing application CLI; do not invent JSON keys or use a password as an encryption key. Preserve and back it up separately from the database. |

Follow the exact creation commands for [Windows PowerShell](database.md#windows-powershell) or
[Linux](database.md#linux-shell), then [generate the identity keyring](database.md#generate-the-identity-keyring).
These procedures generate passwords without printing them and refuse to overwrite existing files.
Protect the host directory with filesystem permissions; Compose mounts individual files under
`/run/secrets`. Values do not belong in `.env`, Docker build arguments or command-line passwords.

Changing a PostgreSQL password file does not change a role already stored in an existing database.
Plan SQL credential rotation explicitly; do not regenerate secrets or delete volumes to fix login.
Identity key rotation has its own [maintenance procedure](authentication.md).

## PostgreSQL and connection pool

| Variable | Template/default | Meaning |
| --- | --- | --- |
| `DB_NAME` | `sophikron` | Database name created on first initialization. Keep it stable; changing this does not rename or migrate an existing database. |
| `DB_POOL_SIZE` | `5` | Normal connection pool size per backend process. |
| `DB_MAX_OVERFLOW` | `5` | Additional connections permitted above the pool size during load. Account for all workers when sizing PostgreSQL capacity. |
| `DB_POOL_TIMEOUT` | `5` seconds | Maximum wait for an available pooled connection. |
| `DB_POOL_RECYCLE` | `1800` seconds | Age after which a pooled connection is replaced when next checked out. |
| `DB_CONNECT_TIMEOUT` | `5` seconds | PostgreSQL connection establishment timeout. |
| `DB_STATEMENT_TIMEOUT_MS` | `10000` ms | Statement execution deadline for the backend. The migration service separately uses 60000 ms. |
| `DB_LOCK_TIMEOUT_MS` | `2000` ms | Maximum database lock wait. |
| `DB_IDLE_TRANSACTION_TIMEOUT_MS` | `30000` ms | Maximum idle time while a transaction remains open. |
| `DB_HEALTH_TIMEOUT` | `2` seconds | Overall deadline for the API's PostgreSQL readiness check. |

Keep the template settings for a local trial. Timeouts bound different operations; increasing one
does not necessarily increase the others. See [database architecture](database.md) for connection
ownership, transactions and the separation between runtime and migration SQL accounts.

## Authentication sessions and admission limits

| Variable | Template/default | Meaning |
| --- | --- | --- |
| `AUTH_SESSION_SECONDS` | `28800` seconds | Absolute session lifetime, eight hours. |
| `AUTH_IDLE_SECONDS` | `1800` seconds | Inactivity lifetime, thirty minutes; activity does not extend the absolute lifetime. |
| `AUTH_LOGIN_IP_LIMIT` | `20` | Failed login budget per IP and rate window. Consider shared school networks when changing it. |
| `AUTH_LOGIN_IDENTITY_LIMIT` | `5` | Failed login budget per IP and normalized supplied identifier. It is not a global account lockout. |
| `AUTH_RATE_WINDOW_SECONDS` | `900` seconds | Fixed failure-counting window. |
| `AUTH_LOGIN_RESERVATION_SECONDS` | `120` seconds | Expiry of abandoned in-flight login reservations. |
| `AUTH_PASSWORD_QUEUE_SIZE` | `8` | Additional queued password jobs per backend process. |
| `AUTH_PASSWORD_QUEUE_TIMEOUT_SECONDS` | `5` seconds | Maximum wait for an available password worker. |
| `AUTH_REQUEST_MAX_BYTES` | `16384` bytes | Backend authentication/admin JSON request body limit before decoding. It does not set the binary document upload limit or the separate frontend body guard. |
| `AUTH_REQUEST_BODY_TIMEOUT_SECONDS` | `10` seconds | Backend deadline for reading these small request bodies. |

Use the defaults unless a measured need justifies changing them. Queue capacity does not change
password hashing concurrency. Native hashing settings and validation bounds are documented in
[authentication configuration](authentication.md#keys-and-configuration); settings not forwarded by
Compose cannot be overridden merely by adding them to `.env`.

## Private document storage

All sizes below are bytes; 1 MiB = 1048576 bytes and 1 GiB = 1073741824 bytes.

| Variable | Template/default | Meaning |
| --- | --- | --- |
| `DOCUMENT_COURSE_QUOTA_BYTES` | `1073741824` (1 GiB) | Logical storage quota per course. |
| `DOCUMENT_USER_QUOTA_BYTES` | `5368709120` (5 GiB) | Logical storage quota per uploader. |
| `DOCUMENT_TOTAL_QUOTA_BYTES` | `21474836480` (20 GiB) | Installation-wide logical document quota. |
| `DOCUMENT_RESERVE_BYTES` | `268435456` (256 MiB) | Free disk space to preserve before accepting an upload. |
| `DOCUMENT_MAX_CONCURRENT_DOWNLOADS` | `16` | Active downloads per backend process; extra requests wait for a slot. |

These settings do not resize the Docker volume or set the per-format upload limit. File format
limits and storage behavior are described in [private documents](lessons.md#private-lesson-documents-storage-and-operations).
The image filesystem is read-only, but `/var/lib/sophikron/documents` is a writable persistent
volume. `/tmp` is ephemeral and separate. Back up database metadata and document bytes together.

## Calendar feeds

| Variable | Template/default | Meaning |
| --- | --- | --- |
| `AUTH_CALENDAR_FEED_LIMIT_PER_MINUTE` | `5` | Request budget per valid calendar subscription over a 60-second window. Exceeding it returns 429 with a retry delay. |

See [calendar subscriptions](timetable.md) for eligibility, private subscription URLs and revocation.

## Invitations and SMTP

| Variable | Template/default | Purpose and what to enter |
| --- | --- | --- |
| `AUTH_MANUAL_INVITATIONS_ENABLED` | `true` | Enables the legacy manual-only invitation endpoint. The administrator's unified access-invitation action also supports manual fallback when SMTP is disabled. This flag is not a global prohibition on manual delivery. |
| `AUTH_MAIL_TRANSPORT` | `disabled` | Use `disabled` for local trials; use `smtp` to send invitations through a mail server. |
| `AUTH_SMTP_HOST` | Empty | SMTP provider hostname, required with `smtp`. |
| `AUTH_SMTP_PORT` | `587` | Provider port, commonly 587 with STARTTLS or 465 with implicit TLS. Follow the provider's settings. |
| `AUTH_SMTP_SECURITY` | `starttls` | `starttls` or `tls`; there is no plaintext transport option. |
| `AUTH_SMTP_USERNAME` | Empty | Provider username when authentication is required. Its presence enables mounting the `smtp_password` file into the backend. |
| `AUTH_SMTP_SENDER` | Empty | Sender address accepted by the provider, required with `smtp`, for example `school@example.org`. |
| `AUTH_ACTIVATION_URL` | Empty | Activation page URL, required with `smtp`: `http://localhost:3000/activate` locally or `https://school.example.org/activate` in production. No query or fragment; account tokens are added separately. |

Enabling SMTP requires host, sender and activation URL. If authentication is used, configure both
the username and password file. Keep all six host secret files present regardless of transport.
Use exact URLs matching the installation; changing SMTP credentials never requires putting a
password in this configuration file.

## Optional Docker network overrides

| Variable | Default | Meaning |
| --- | --- | --- |
| `BFF_SUBNET` | `172.30.85.0/24` | Private Docker subnet for frontend/API communication. Change only if it conflicts with another host, VPN or Docker network. |
| `BFF_ADDRESS` | `172.30.85.2` | Fixed frontend container address, also used by Uvicorn to trust forwarding headers. |
| `API_ADDRESS` | `172.30.85.3` | Fixed API container address. |

Leave these commented for a normal local trial. If overriding them, choose a non-conflicting subnet
and two different usable addresses inside it. These are container addresses, not the host's LAN IP.
The browser continues using localhost. Preserve a consistent Compose project name to reuse volumes.

## Build metadata and settings controlled by Compose

`SOPHIKRON_BUILD_REVISION` is generated by [build.ps1](../build.ps1) from the local Git checkout.
The script sets it temporarily for both builds and restores the environment afterwards. Do not
store it in `.env`. Direct Compose builds without an explicit revision use `unknown`. Versions
come from the backend package and frontend `package.json`, not from a runtime environment value.

Compose fixes or derives the following settings; they are not ordinary root `.env` options:

| Settings | Source and effect |
| --- | --- |
| `AUTH_ENVIRONMENT` | Base: `production`. Local overlay: `${AUTH_ENVIRONMENT:-development}`; the isolated test launcher uses `test`. Existing local values remain effective. |
| `AUTH_COOKIE_SECURE`, `AUTH_CORS_ENABLED` | Base forces `true`/`false`; local overlay forces `false`/`true`. Root `.env` assignments do not override those literals. |
| `AUTH_ALLOWED_ORIGINS` | Derived from the selected application origin and local API origins. A legacy `.env` assignment does not override this expression. Native processes instead need a JSON array of exact origins. |
| `ORIGIN`, `SITE_ORIGIN` | Frontend runtime/build settings derived from `SOPHIKRON_ORIGIN` and the local frontend port. |
| `BACKEND_ORIGIN` | Frontend server uses Docker DNS `http://backend:8000`. Browser requests go through the frontend. |
| `DB_HOST`, `DB_PORT`, `DB_SSLMODE` | Docker database hostname `db`, internal port 5432 and unencrypted transport inside the selected Docker network. |
| `DB_USER`, `DB_PASSWORD_FILE` | Service-specific SQL role and mounted credential path. The API never receives the migration or cluster administrator password. |
| `AUTH_KEYS_FILE`, `AUTH_BOOTSTRAP_PASSWORD_FILE`, `AUTH_SMTP_PASSWORD_FILE` | Internal mounted paths, with the SMTP path enabled only when a username is configured. |
| `DOCUMENT_ROOT` | Fixed writable document volume path. |
| `ADDRESS_HEADER` | Production frontend trusts the host proxy's `X-Real-IP`; local frontend ignores browser forwarding headers. |

Older local `.env` files can contain `AUTH_ENVIRONMENT`, `AUTH_COOKIE_SECURE` and
`AUTH_ALLOWED_ORIGINS`; preserve values when reorganizing, but use the rules above to understand
which ones Compose actually consumes. Native execution can use these settings directly.

## Applying changes

- For ordinary runtime settings, recreate services with `docker compose -f compose.yaml -f compose.local.yaml up -d --wait` locally. A simple `restart` does not reload container environment.
- For the frontend origin or build metadata, rebuild as well: `./build.ps1 -Local -Start`.
- For production, omit `-Local` and the local Compose overlay; configure HTTPS and the host proxy.
- Database names, SQL passwords and encryption keys require their specific initialization or rotation procedure. Recreating containers does not migrate these persistent identities.

Do not delete volumes or replace secret files as a routine configuration update.
