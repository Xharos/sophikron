# ADR 0005: Fresh release baseline and installation configuration

- **Status:** Accepted
- **Date:** 2026-10-30
- **Sources:** `backend/alembic/versions/0001_authentication.py` through `0007_timetable.py`,
  especially `0002_configuration.py`; `app/services/releases.py`.

## Context and decision

The release baseline contains seven ordered feature revisions, with `0007_timetable` as the only head.
Configuration includes the singleton release-check cache. This is a fresh
installation baseline, not an upgrade path for any database that used an earlier amended history.
Do not use `stamp` to make such a database appear compatible. Published revisions become immutable.

Configuration owns `site_settings`, `api_metrics` and `release_check`. Site settings and release cache
use a seeded singleton row. API monitoring aggregates bounded minute/category measurements without
foreign keys to users or teaching data. The release cache holds one installation-wide result rather
than requesting GitHub from each browser or keeping inconsistent worker-local caches.

The versions endpoint requires `users.manage`. A PostgreSQL advisory lock coordinates refreshes;
successful and failed attempts are limited to once per rolling 24 hours. The fixed public HTTPS
lookup sends no credentials or student data. Outages preserve the last success. Updates remain manual.

## Consequences and alternatives

`alembic upgrade head` creates the full installation in dependency order. Downgrading configuration
removes settings and these measurements/cache; it is not a way to undo only the release check.
Keeping a separate 0008 would preserve the old chain but obscure this pre-release consolidation.
The migration-stage integration test checks the cache is absent at 0001 and seeded at 0002;
round-trip and metadata checks validate the full PostgreSQL schema. The runtime cannot access
Alembic's version table and never receives the migration password.

See [migration inventory and compatibility](../database.md#migrations).
