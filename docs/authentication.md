# Backend authentication

Sophikron authenticates local accounts using Argon2id passwords and opaque server sessions. There is
no public registration, bearer JWT, public password recovery or MFA. Administrators can issue
password-reset invitations. The SvelteKit frontend uses
a server-side BFF; see [frontend and BFF](frontend-bff.md) for deployment and trust boundaries.
Backend authorization is mandatory regardless of what a client displays.

## Data and encryption

Identity fields and optional private school-profile fields in `sophikron.users` are reversibly
encrypted: username, email, first/family names, birth date, location, prior school, baccalaureate,
orientation, phone and the reference adult. See [school profiles](administration.md#complete-school-profiles)
for columns and permissions. AES-256-GCM uses a new random 96-bit nonce per encryption, a versioned keyring, and
associated data binding the ciphertext to the integer account ID, field and key version. Ciphertext moved
between accounts or fields cannot be authenticated. The application decrypts only authorized response
fields and the recipient address needed for SMTP delivery. Encryption is not end-to-end: the backend
has the keys. It protects identity contents in a database-only disclosure, not a compromised backend.

Generated usernames follow [the account creation rule](administration.md#account-identities).
For login normalization, usernames are trimmed, lowercased ASCII identifiers of 3–64 characters: letters, digits, `_`, `-`, `.`;
the first character must be a letter or digit. `@` is reserved for email login. Emails are validated
without DNS queries and normalized; treating the entire address as case-insensitive is an intentional
product policy. No provider-specific removal of dots or `+` suffixes is performed.

Separate, domain-separated HMAC-SHA-256 lookup values enforce database uniqueness and exact identity
search without storing plaintext. They leak equality, and remain pseudonymous data. Substring SQL search
and alphabetical SQL sorting are unavailable. Authorized partial/fuzzy name search is implemented
in transient backend memory; see [administration](administration.md#interactive-search). The lookup key is distinct from encryption keys.

Passwords use salted Argon2id PHC strings, never reversible encryption. Defaults are 64 MiB, three
iterations and four lanes, with two concurrent password workers per API process. New permanent
passwords are 10–128 characters, drawn exclusively from `a-z`, `A-Z`, `0-9` and ASCII punctuation
(`!"#$%&'()*+,-./:;<=>?@[\]^_` plus backtick, `{|}~`). Each password must contain at least one
lowercase letter, uppercase letter, digit and punctuation character. Spaces, accents, emoji and
control characters are rejected. Passwords are never trimmed or interpreted as code. There is no
dictionary/breached-password check or periodic-change requirement. Existing hashes remain usable
until password replacement. Successful login rehashes when configured Argon2 parameters change.

The bootstrap secret is separate: it may be empty or simple in any environment, but must come from
the configured file (maximum 128 characters and 512 UTF-8 bytes, without embedded newline or NUL).
An empty login password is therefore accepted by the request schema; it does not bypass verification.

Sessions and invitations contain only full SHA-256 verifiers of random 256-bit tokens. Integer row IDs are not
authentication credentials. Roles, account status, timestamps, counters and integer relationships are
readable database metadata. `activity_events` does not collect IPs, user-agents or navigation history.
The current session table also omits these optional device metadata fields.

## Keys and configuration

From `backend/`, generate a keyring once into a private directory you already created:

```sh
python -m app.cli generate-keys --output /private/sophikron/identity_keys.json
```

Use the configured Python interpreter. The command never overwrites a file or prints key values.
On Windows choose an appropriate local absolute path and protect its parent directory using ACLs.
On Linux restrict directory access and make the mounted secret readable by container UID `10001`.
The application refuses to start without a valid keyring. Keys are never generated during API startup.

Store `identity_keys.json` directly inside `SOPHIKRON_SECRETS_DIRECTORY` for Compose, which mounts it
at `/run/secrets/identity_keys`. Direct Python processes use `AUTH_KEYS_FILE`. Like `DatabaseSettings`,
`AuthSettings` reads process environment variables, not dotenv files. Compose reads `.env` and passes
only the variables explicitly configured in its service. The repository uses the production base
`compose.yaml`, the explicit local overlay `compose.local.yaml`, and one private `.env`. No extra
environment template is needed. See [BFF deployment](frontend-bff.md#production-topology).
Settings such as pool limits, session durations, browser origins and SMTP options live in `.env`.
An empty YAML value such as `AUTH_SESSION_SECONDS:` is an allowlisted pass-through: Compose resolves
it from the shell first, then `.env`. If absent from both, it is omitted and the application default
applies. This keeps the Compose file readable without injecting every `.env` variable into containers.
Internal database roles, mounted secret paths and conditional SMTP/bootstrap paths stay in Compose.

For local development, add the needed paths and options to that `.env`. This example contains no
secret values; keep passwords and keys in separate protected files:

```dotenv
DB_NAME=sophikron
SOPHIKRON_SECRETS_DIRECTORY=/private/sophikron
AUTH_BOOTSTRAP_USERNAME=setup_operator
AUTH_ENVIRONMENT=development
AUTH_COOKIE_SECURE=false
AUTH_ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:8000"]
```

Define `SOPHIKRON_SECRETS_DIRECTORY` in the root `.env` before starting Compose. Compose reads it
when resolving host paths; it is not generated at startup or passed to application code. A shell
environment value takes precedence. All six secret files live directly in this directory:
`db_admin_password`, `db_app_password`, `db_migration_password`, `identity_keys.json`,
`bootstrap_password` and `smtp_password`. Each service receives only its declared files.

Provide `bootstrap_password` with a private installation password, and `smtp_password` with the
optional SMTP password
(or an empty file while SMTP is disabled). Compose mounts both files read-only only in the backend.
No host directory is mounted, and there is no `runtime` folder or initial-invitation output file.
The bootstrap username is the only bootstrap setting in `.env`; its password is never an env value.
After setup, its file may be emptied; the Compose mount still requires a file to exist.

| Setting | Default / purpose |
| --- | --- |
| `AUTH_KEYS_FILE` | Required versioned JSON keyring file |
| `AUTH_ALLOWED_ORIGINS` | Required JSON array of exact origins, without trailing slash |
| `AUTH_CORS_ENABLED` | `true` by default; production Compose disables browser CORS independently of CSRF |
| `AUTH_MANUAL_INVITATIONS_ENABLED` | Controls the legacy manual-only endpoint; automatic access invitations use manual delivery when SMTP is disabled |
| `AUTH_ENVIRONMENT` | `production`; local `.env` sets `development` |
| `AUTH_COOKIE_SECURE` | `true`; local HTTP `.env` sets `false` |
| `AUTH_SESSION_SECONDS` | `28800`, absolute eight-hour lifetime |
| `AUTH_IDLE_SECONDS` | `1800`, thirty-minute inactivity lifetime |
| `AUTH_INVITATION_SECONDS` | `172800`, maximum 48 hours; lower values allowed for tests |
| `AUTH_ARGON_MEMORY_KIB` | `65536` |
| `AUTH_ARGON_ITERATIONS` | `3` |
| `AUTH_ARGON_PARALLELISM` | `4` |
| `AUTH_PASSWORD_WORKERS` | `2`, per-process memory/CPU concurrency bound |
| `AUTH_PASSWORD_QUEUE_SIZE` | `8` additional admitted password jobs per process |
| `AUTH_PASSWORD_QUEUE_TIMEOUT_SECONDS` | `5`, maximum wait for a password worker |
| `AUTH_REQUEST_MAX_BYTES` | `16384`, maximum authentication/admin request body before JSON parsing |
| `AUTH_REQUEST_BODY_TIMEOUT_SECONDS` | `10`, total authentication/admin body-read deadline |
| `AUTH_RATE_WINDOW_SECONDS` | `900` |
| `AUTH_LOGIN_IDENTITY_LIMIT` | `5` failed logins per IP/normalized supplied identifier |
| `AUTH_LOGIN_IP_LIMIT` | `20` failed logins per IP across identifiers; consider shared school networks |
| `AUTH_LOGIN_RESERVATION_SECONDS` | `120`, recovery deadline for abandoned in-flight login leases |
| `AUTH_MAIL_TRANSPORT` | `disabled` or `smtp` |
| `AUTH_SMTP_HOST`, `AUTH_SMTP_PORT` | SMTP server; default port `587` |
| `AUTH_SMTP_SECURITY` | `starttls` or `tls`; certificates are verified |
| `AUTH_SMTP_SENDER` | Required when SMTP is enabled |
| `AUTH_SMTP_USERNAME`, `AUTH_SMTP_PASSWORD_FILE` | Optional paired SMTP credentials |
| `AUTH_ACTIVATION_URL` | Trusted client activation page URL, required for SMTP |
| `SOPHIKRON_SECRETS_DIRECTORY` | Required Compose host root for all six secret files |
| `AUTH_BOOTSTRAP_USERNAME` | Required until installation is complete; ignored afterwards |
| `AUTH_BOOTSTRAP_PASSWORD_FILE` | Direct-process secret path; Compose fixes `/run/secrets/bootstrap_password` |

Production settings require HTTPS origins, secure cookies and adequate password hashing parameters.
Serve the API over HTTPS behind a trusted reverse proxy; this local Compose stack does not terminate
TLS. Configure the proxy's traffic limits and the ASGI server's trusted forwarded IPs explicitly.
Never trust arbitrary `X-Forwarded-For` headers or expose a bypass around the proxy's limits.

Keep protected, separately stored backups of every key needed by database backups. Losing keys makes
the associated identities unreadable. Do not remove old keys while older backups still require them.

### Local and production key management

The JSON keyring contains the actual AES keys and a separate HMAC lookup key, encoded as Base64;
Base64 is not encryption. Local Compose secrets mount this host file read-only, but do not encrypt
it on the host. The backend loads it into memory at startup; replacing the file requires restarting
every API worker. There is currently no KMS/Vault integration, automatic rotation or automatic
key recovery. Neither `.env`, PostgreSQL nor the container image contains these key values.

For local development, generate a dedicated keyring once, protect its directory with filesystem
permissions, and reuse it with the same development database. Do not regenerate keys at each start
or use production keys/data locally. Unit and isolated integration tests use their own synthetic keys.

For production, provision a separate keyring through a protected secret store or tightly controlled
secret files. Grant the API access and exclude the database/migration services. Keep recoverable,
access-controlled copies apart from database backups, and test restoring a matching database/keyring
pair. All API replicas using the same database must share the appropriate key versions. Rotation is
the explicit maintenance procedure below; replacing the keyring with unrelated keys breaks identity
decryption and exact-login lookup.

Disk/storage encryption protects stored blocks when its key is unavailable. It does not hide fields
from an authenticated SQL reader or ordinarily encrypt a logical SQL dump. Application encryption
adds protection for all four identity fields in a database-only disclosure; account metadata stays readable.
The current Compose volume does not configure disk encryption: that depends on the host or database
provider and must be verified for deployment. HTTPS and database TLS protect network traffic and
are separate requirements. An attacker controlling the backend or host may obtain both data and keys.

### Key rotation

For encryption-key overlap, add a new random key under a new version, keep existing versions and switch
`active_key`. New encryption uses the new version; old versions remain readable. Keep `lookup_key`
unchanged unless deliberately rotating lookup indexes too.

To re-encrypt stored users, including an intentional HMAC-key change:

1. Stop all API workers and other account writers for maintenance.
2. Preserve the previous keyring separately and configure `AUTH_KEYS_FILE` with the new keyring.
3. With application-role database settings run:

   ```sh
   python -m app.cli rotate-identities --previous-keys-file /private/previous.json --maintenance
   ```

4. The command verifies the previous indexes, locks accounts and atomically replaces encrypted fields
   and lookup values. Failure rolls back the transaction. Use a maintenance window appropriate to the
   account count; this first implementation rotates the table in one transaction.
5. Restart every API worker with the new keyring. Verify login and retain old keys for backup recovery.

An HMAC-key change also changes rate-limit keys and therefore begins new attempt budgets. This is an
explicit maintenance action. Encryption does not encrypt timestamps, roles or login statistics.

## Initial administrator

Configure `.env`, the three PostgreSQL passwords, the identity keyring and the two secret files
above, then start the normal stack from the repository root:

```sh
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

These are local instructions; production uses only `compose.yaml` behind an HTTPS host proxy.
For prebuilt images, omit `--build`. With source builds, rebuild
images after code changes. PostgreSQL becomes healthy first, then the one-shot migration service
runs `alembic upgrade head` using only the migration-role password. The API starts only after that
service exits successfully; the frontend waits for API health. A migration failure prevents API
startup. No `--wait`, manual migration command or data reset is needed.
The detached command returns before readiness; inspect `docker compose ps` and logs for progress.
The API retries failures at most three times rather than looping forever on invalid setup settings.

`sophikron.application_state` contains exactly one row (`id=1`), with nullable `initialized_at`.
Until completion the backend requires a nonempty valid `AUTH_BOOTSTRAP_USERNAME`. On a fresh empty
database it reads the bootstrap password file, hashes it using Argon2id, and creates one active
48-hour temporary administrator. This account has no email. A missing username or invalid secret
stops first installation with an explicit diagnostic. Concurrent workers serialize creation.

The installation secret is intentionally exempt from permanent password composition rules, including
in production. Empty and simple installation secrets are accepted at the owner's explicit request.
The account still expires after 48 hours and is permanently retired by setup. No default password is
embedded in source, image or tracked configuration.

The temporary account can log in, inspect `/auth/me`, log out, and call `POST /api/v1/auth/setup`.
It cannot create/invite ordinary accounts or change passwords. Complete setup with:

```json
{"first_name":"Valentin","last_name":"Burgaud","email":"operator@example.org","password":"ExampleAdminPassword2026!"}
```

Roles cannot be supplied. The service creates an active permanent administrator, sets
`initialized_at`, disables the temporary account, clears its password hash and revokes its sessions
and outstanding invitations in one transaction. Failure, including duplicate identities, rolls back
all changes so setup remains retryable. The permanent email is not marked verified without mailbox
proof. No SMTP delivery is required to finish setup. The response is `201` and clears the bootstrap
cookie; explicitly log in with the generated username returned in the profile, or email, afterwards.

After completion, remove `AUTH_BOOTSTRAP_USERNAME` from `.env` if desired; leaving it is harmless.
Restarts do not recreate the bootstrap even if its disabled record is removed. Changes to the secret
file never silently reset an existing account or extend its deadline. If unfinished setup expires,
explicit local recovery can use the configured username and current password secret:

```sh
docker compose run --rm --no-deps backend python -m app.cli bootstrap --renew
```

Recovery resets only an existing unfinished bootstrap and revokes its previous credentials. It is
refused once installation is complete. Legacy invitation-based bootstrap accounts are preserved;
use this explicit recovery command to switch them to password login rather than expecting an
automatic credential reset. The consolidated migration targets fresh databases; it does not upgrade
previously populated development variants. An inconsistent account set fails closed and requires
operator inspection.

### Manual verification in Swagger

Open `http://localhost:8000/docs`, using an origin listed in `AUTH_ALLOWED_ORIGINS`. Every POST
operation documents the `X-CSRF-Protection` header: enter `1` in that field before Execute.
No JavaScript console workaround or pasted cookie is required. ReDoc is reference documentation.

1. `GET /api/v1/auth/me` returns `401` before login.
2. `POST /api/v1/auth/login` with the bootstrap username and secret returns `200`; the browser stores
   the HttpOnly cookie automatically. Do not use Swagger's Authorize field to copy session tokens.
3. `GET /api/v1/auth/me` returns the temporary profile, including `is_bootstrap=true`, `email=null`.
4. `POST /api/v1/auth/setup` with permanent credentials returns `201` and ends temporary access.
5. Bootstrap login and its old sessions return `401`; permanent login returns `200`.
6. The permanent administrator can create pending accounts and generate manual invitations when
   enabled, or send invitations once SMTP is configured.
7. `POST /auth/change-password` revokes all sessions; `POST /auth/logout` revokes the current session.
   An expired/revoked session or inactive account always produces `401` on protected routes.

## API and authorization

| Method and path | Access | Success |
| --- | --- | --- |
| `POST /api/v1/auth/login` | Public, browser request protection | `200` profile and session cookie |
| `POST /api/v1/auth/activate` | Public, invitation token and browser protection | `204` |
| `GET /api/v1/auth/me` | Active authenticated account | `200` own profile, roles and account activity |
| `GET /api/v1/auth/me/promotions` | Active permanent account | `200` own promotion badges |
| `POST /api/v1/auth/logout` | Active authenticated account | `204`, revoke current session |
| `POST /api/v1/auth/setup` | Temporary administrator only | `201`, permanent profile; bootstrap cookie removed |
| `POST /api/v1/auth/change-password` | Active permanent account, current password | `204`, revoke all sessions |
| `POST /api/v1/admin/users` | Administrator | `201`, pending profile |
| `POST /api/v1/admin/users/{user_id}/invite` | Administrator | `204`, message accepted by transport |
| `POST /api/v1/admin/users/{user_id}/manual-invitation` | Permanent administrator, explicit setting | `200`, new token and expiry |
| `POST /api/v1/admin/users/{user_id}/access-invitation` | Permanent administrator | `200`, automatic SMTP or manual delivery; activation or reset |

Login JSON is `{"identifier":"username-or-email","password":"..."}`. Activation JSON is
`{"token":"...","password":"..."}`. Password change uses `current_password` and `new_password`.
Setup accepts `first_name`, `last_name`, `email` and `password`. Normal account creation accepts
`first_name`, `last_name`, `email`, an explicit nonempty `roles` array and optional `promotion_ids`.
Usernames are generated once from French names and a random suffix 100–999, never supplied or
modified by the caller. See [administration](administration.md) for validation and dashboard routes. Passwords,
status and privileged flags cannot be supplied during creation. Responses never contain password
hashes, token verifiers, lookup values or session secrets. There are no public registration,
role-management, session-list or logout-all routes in this increment. The admin activity journal
is available under `/api/v1/admin/events`.

The own-account `/me` response additionally includes `updated_at`, `last_login_at`,
`password_changed_at`, `email_verified_at` and `login_count`, read from the existing account row.
These fields are not added to login or administrator account-creation responses. No account ID
supplied by a client selects another profile: `/me` always uses the authenticated session's account.

`AuthenticatedUser` is `Annotated[UserContext, Depends(get_current_user)]`. `AdminUser`, `TeacherUser`
and `UserAccount` require explicit `users.manage`, `teacher.access` and `user.access` permissions.
Use `Annotated[UserContext, Depends(RequirePermission("promotions.manage"))]` for capability policies.
Role-only checks remain available for exceptional policies through `RequireRole`.

Every check requires an active account and valid session. Roles and permissions are loaded on each
request; an administrator does not implicitly inherit teacher/user capabilities. Allowed roles are
`user`, `kholleur`, `teacher`, `admin`, or `teacher + admin`; student and khôlleur roles stand alone.
Sensitive services recheck actor capabilities inside their transaction. Protected routes inherit
browser write protection; public write routes explicitly include `Depends(require_csrf)`.

Status `401` means a missing/invalid session or inactive account; `403` means insufficient permission
or rejected browser request; `429` includes `Retry-After`. Login failures use the same status and
message for unknown, pending, disabled and incorrect-password accounts. Missing/malformed request
fields produce generic `422` responses without Pydantic input echoes. Invitation failures use one
generic `400`; database failures return anonymous `503` responses. No credentials are logged.

## Cookies, CSRF and inactivity

Cookies are host-only, `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` in production. Secure cookies
use `__Host-sophikron_session`; explicitly insecure local tests use `sophikron_session_dev`. A new
login replaces an existing same-browser session for the same account. Other browsers/devices retain
their independent sessions. Logging out revokes only the current one. Password change revokes all.

Every modifying request, including login and activation, must include:

```http
Origin: https://your-trusted-client.example
X-CSRF-Protection: 1
Content-Type: application/json
```

The content type is required when there is a body. The custom header relies on browser preflight,
exact credentialed CORS origins for direct browser API access, and server-side origin validation.
CORS is disabled for the private production API; origin validation remains active. The BFF validates
the public origin before supplying these backend headers. `Referer` supplies the origin only
when `Origin` is absent; absent/null/untrusted origins are rejected. CLI clients must supply these
headers too. Unauthenticated protected operations still return `401` before browser checks.

The session expires at the earlier of its absolute deadline and last authenticated request plus the
inactivity duration. One session timestamp is updated; mouse movement, keystrokes and page history
are not collected. Reading a long page without backend requests counts as inactivity; polling can
keep a session active. This is a server-request timeout, not proof of human presence. Closing a tab
or browser is not reliable logout; server expiry remains authoritative even if cookies are restored.

Login limits count only failed authentication, including unknown/inactive accounts and incorrect
passwords. The defaults allow five failures per IP/identifier and twenty per IP. Each fixed window
starts when its first failure is recorded and resets entirely 900 seconds later; later failures and
blocked requests never extend it. Successful login neither consumes an attempt nor clears earlier
failures. Another IP has independent budgets; no account-global lock exists. Multiple users sharing
one public IP also share its twenty-failure budget.

The IP budget is checked before querying users. Pair keys use the normalized supplied identifier,
not a resolved integer account ID, so username and email aliases cannot reveal their relationship via a
shared account counter. Unknown identifiers follow the same path. Keys are HMAC-protected; plaintext
IPs and identifiers are not stored in these tables. Temporary `login_attempts` leases reserve capacity
under PostgreSQL row locks to prevent concurrent guesses overrunning the limits. Completion releases
the lease; only a credential rejection records a failure. Saturation, cancellation and server errors
do not count as credential failures. A crashed worker's lease expires after 120 seconds. Admission
can temporarily return `429` while verification slots are reserved, including before any failure.

Activation, password change, setup and invitation delivery retain separate attempt budgets using
the same configured limits and window; their quotas count operations, including successful ones.
Reverse-proxy volumetric limits remain complementary.

Authentication and admin bodies are limited before JSON parsing, checking both declared and actually
received bytes, including chunked requests. Oversize returns generic `413`, malformed Content-Length
returns `400` and a body-read deadline returns `408`. Exactly-at-limit bodies proceed to ordinary
validation. Password jobs have bounded admission and queue wait; overload returns generic `503` with
`Retry-After: 1`. Running Argon2 jobs finish safely rather than abandoning memory-intensive threads.

An exhausted IP budget is checked before creating an identity counter. Periodically remove expired
ephemeral counters with `python -m app.cli prune-rate-limits`, using application-role settings.
This existing maintenance command also removes expired login leases, preserves live reservations,
and never removes users, sessions or login history.

## Invitations and mail

`InvitationMailer` is injectable. The default disabled adapter fails explicitly. `SmtpMailer` supports
verified STARTTLS or TLS and optional credentials from a mounted secret file; it imposes no vendor.
Configure SMTP in the same `.env`, for example:

```dotenv
AUTH_MAIL_TRANSPORT=smtp
AUTH_SMTP_HOST=smtp.example.org
AUTH_SMTP_PORT=587
AUTH_SMTP_SECURITY=starttls
AUTH_SMTP_SENDER=noreply@example.org
AUTH_SMTP_USERNAME=sophikron
AUTH_ACTIVATION_URL=http://localhost:3000/activate
```

If SMTP authentication is required, store its password in the protected file
`smtp_password` inside `SOPHIKRON_SECRETS_DIRECTORY`. Compose maps it to
`/run/secrets/smtp_password` when
`AUTH_SMTP_USERNAME` is set. Omit the username for a TLS relay that does not require credentials.
Direct Python processes can set `AUTH_SMTP_PASSWORD_FILE` to their own protected file path.
Do not put credential values in `.env`.

Only one outstanding invitation exists per account. Explicit resend revokes all previous unused
links, including expired ones. No automatic resend or extension occurs. Expiration is checked at
use, so a cleanup job is not required to reject an expired link. Activation checks again under locks
after password hashing and atomically consumes the token. Invitations carry a validated purpose:
`activation` for pending accounts, `reset` for active accounts. Both use `/auth/activate`; disabled
accounts cannot consume either. Reset changes the password, revokes every session and outstanding
invitation, and records `auth.password_reset`. Issuing a reset leaves the existing password usable
until the link is consumed. Archiving revokes links and sessions immediately.

The dashboard calls `/admin/users/{id}/access-invitation`: SMTP is chosen when configured; otherwise
it returns the new token and expiry for manual sharing, independently of the legacy manual-only
setting. SMTP responses contain no token. Transport errors return 503 and revoke the failed link;
they do not silently downgrade to manual delivery. Pending and active accounts share the same flow,
with UI labels for first activation, resend/expiry and password reset.

The invitation is committed before SMTP; no SQL transaction is held during network IO. A known or
uncertain transport failure revokes that link and returns a generic error. A crash can leave an
unsent invitation record: explicit resend safely replaces it. This increment does not promise
transactional email delivery or add an outbox storing plaintext invitation secrets.

SMTP links place the token in a URL **fragment**, not a query string, to keep it out of ordinary
access logs. The eventual client activation page must read the fragment and POST it in JSON. That
page is implemented at `/activate` by SvelteKit. Manual delivery never marks email as verified.
See [invitations and password resets](frontend-bff.md#invitations-and-password-resets).

## Activity and login statistics

Each successful authentication increments `users.login_count`, updates `last_login_at`, inserts an
`activity_events` fact of type `auth.login_succeeded` and creates its session in one transaction.
The event actor and subject are the authenticated account. Failed attempts and ordinary navigation
do not increment counts. Session deletion does not remove the journal.

Filter by event type and use `subject_user_id` for per-account login reports. Choose explicit
timezone boundaries for reporting periods; a login event is not proof of human presence. Events do
not repeat personal identities, IPs or navigation data. Define retention before production; no
automatic history deletion is implemented. See [activity journal](administration.md#activity-journal).

## Reconstructed Alembic revisions

The owner explicitly authorized rebuilding the baseline after deleting the local volumes.
The migration chain is:

1. `0001_authentication`: accounts, roles/permissions, sessions, invitations, setup, login
   protection and the append-only activity journal.
2. `0002_configuration`: public site settings, shared holiday color, timelines and events.
3. `0003_promotions`: promotion catalogue and account memberships.
4. `0004_subjects`: subject catalogue and account subject assignments.
5. `0005_lessons`: course pages, content, responsibility, collaborations and promotion access.

Use `alembic upgrade head` on a fresh database. These revisions do not upgrade older populated
variants or the old `0001_database_baseline`; historical `adopt-empty-baseline` is removed. No database
is reset automatically. Future applied revisions must not be rewritten without explicit authorization.
Downgrade is destructive and belongs only in an explicitly disposable test database.

## Verification and dependencies

From `backend/`:

```sh
python -m pytest -q -m "not integration"
ruff check .
```

For the complete suite, follow `docs/database.md` to select an isolated `sophikron_test` database,
runtime/migration role secrets and the running API URL; set `DB_INTEGRATION=1`, then run
`python -m pytest -q`. Unit tests use synthetic keys and explicit inexpensive test-only Argon2
parameters. Integration tests exercise actual PostgreSQL and ASGI requests, including role checks,
CSRF, cookies, invitation races, session deadlines/revocation, login counters and key rotation.
Migration tests check downgrade/upgrade and consistency with the final SQLAlchemy metadata.

Added dependencies: `argon2-cffi` (MIT), `cryptography` (Apache-2.0 OR BSD-3-Clause), `email-validator`
(Unlicense), explicit `anyio` (MIT, already used by the framework), and `rapidfuzz` (MIT) for fuzzy name
search. Keep their releases reviewed and maintained; passing these checks is not a comprehensive
security assessment.

