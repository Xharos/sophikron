# ADR 0002: Asynchronous PostgreSQL infrastructure

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

The initial backend used a synchronous engine in asynchronous endpoints, fallback credentials in
source, and one PostgreSQL account. Runtime secrets, migrations and real database tests were needed
before introducing business models.

## Decision

- Use SQLAlchemy 2.x asyncio with psycopg 3 and a single bounded SQLAlchemy pool per process.
- Validate separate environment variables with pydantic-settings and read passwords from Docker
  secret files at startup; never construct URLs through string interpolation.
- Own engines in the FastAPI lifespan and use request/task-specific sessions. Services explicitly
  delimit atomic transactions; dependency teardown never commits and writes are not retried blindly.
- Require migrated installation state and database access at startup; after startup, bound readiness
  checks and return anonymous 503s during outages. This supersedes the initial startup-without-DB design.
- Separate administrator, migration and runtime accounts. Restrict the runtime account to data
  operations in the dedicated application schema; deny access to Alembic version tracking.
- Run Alembic explicitly with the migration account, the shared metadata and an unpooled connection.
  Provision roles separately during database initialization; never automatically reset existing data.
- Keep only the database, API, frontend and migration services in Compose. Run pytest in the local
  Python environment against the full services and a dedicated test database, without a test image.

## Consequences

Configuration errors and an unavailable database stop startup; readiness can recover after a later outage. Secret rotation requires
coordinating PostgreSQL role passwords, mounted files and process restarts. Migrations and provisioning
are explicit operational steps. No business schema, replica orchestration, automatic retries or
encryption of personal data was introduced by this infrastructure decision. Application encryption
was subsequently adopted in ADR 0003/0004. No additional paid infrastructure is required.

## Alternatives

A synchronous engine would retain blocking database calls in asynchronous handlers. Combining
psycopg_pool and SQLAlchemy pooling would add unnecessary lifecycle complexity. A single superuser
account would weaken privilege boundaries. Automatic dependency-level commits would obscure business
transaction boundaries. Disk encryption alone would not protect personal data in a leaked SQL dump.
