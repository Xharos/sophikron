# ADR 0003: Local authentication and encrypted account identities

- **Status:** Accepted; identity IDs, field scope, permissions, events and migration history
  superseded by [ADR 0004](0004-accounts-promotions-activity.md)
- **Date:** 2026-10-21

## Decision

Use local Argon2id credentials, PostgreSQL-backed opaque cookie sessions, and single-use 48-hour
administrator invitations. Expose seven authentication/account routes under `/api/v1`. Keep the
frontend unchanged. Use reusable FastAPI `Annotated` dependencies for active-account and explicit
role requirements; administrators do not implicitly inherit other roles.

Encrypt username/email only in `users`, using AES-256-GCM with row/field/version binding and an
external versioned keyring. Separate HMAC lookup indexes enforce canonical uniqueness and exact
search. Passwords and random tokens use their appropriate one-way hashes. Keep UUIDs, timestamps,
role relations and successful-login events readable for integrity and statistics. Do not collect
navigation, IPs or user agents in the login history.

Combine strict origin checks, custom headers, JSON bodies and exact credentialed CORS for browser
write protection. PostgreSQL attempt reservations coordinate workers; reverse-proxy traffic limits
remain complementary. Use generic public errors and never echo secret input values.

Create a username-only temporary administrator from a mounted installation-password secret.
Persist completion in a singleton application-state row. One authenticated setup operation creates
the permanent administrator without SMTP and atomically retires bootstrap access. Bootstrap env
settings cannot reopen completed setup. At the owner's explicit request the installation secret may
be simple or empty in any environment. Permanent passwords require 10–128 non-space ASCII characters
including lowercase, uppercase, digits and punctuation, without dictionary screening.
Compose gates API startup on database health
and a successful one-shot migration service, without granting DDL credentials to the API.

At the owner's explicit request during development, consolidate authentication and installation
state into one initial migration while retaining its revision ID. This consolidation targets fresh
databases; existing development volumes are reset only with explicit owner authorization. Provide
a guarded compatibility operation for the old empty baseline. Never automatically reset data or
edit future applied migrations without explicit authorization.

The owner additionally authorized updating the initial revision for temporary login leases and
nonnegative failure counters. Login quotas are twenty failures per IP and five per IP/supplied
identifier, configurable through AUTH_* variables, with fixed windows starting at the first failure.
Successful login does not consume or clear failures. No account-global budget links email and username
or blocks access from other IPs. PostgreSQL leases bound concurrent attempts; bounded HTTP bodies and
password queues protect application admission. Existing populated baselines are not silently upgraded.

## Consequences

Operators must protect and back up identity keys separately. Exact identity lookup is available;
substring search and plaintext SQL sorting are not. Key/index rotation requires maintenance in this
initial implementation. SMTP is optional and replaceable; failed delivery is explicit, without a
plaintext-token outbox. Login statistics record successful authentication rather than human presence.
Retention must be selected before collecting production history. MFA, public registration, recovery,
analytics endpoints and a frontend activation page remain separate work.
