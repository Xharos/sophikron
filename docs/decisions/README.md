# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) documenting significant technical and architectural decisions made during the development of Sophikron.

## Accepted decisions

| ADR | Responsibility / migration sources |
| --- | --- |
| [0001](0001-technology-stack.md) | Stack and component separation |
| [0002](0002-postgresql-infrastructure.md) | SQLAlchemy, PostgreSQL roles and Alembic |
| [0003](0003-backend-authentication.md) | Original authentication design, amended by 0004/0005 |
| [0004](0004-accounts-promotions-activity.md) | Accounts, capabilities and activity; 0001/0003 |
| [0005](0005-release-baseline-and-configuration.md) | Seven-revision baseline and configuration/cache; 0002 |
| [0006](0006-teaching-catalogues-and-courses.md) | Promotions, subjects and courses; 0003 through 0005 |
| [0007](0007-private-course-documents.md) | Private storage and document trust; 0005 |
| [0008](0008-groups-timetables-and-calendar-feeds.md) | Groups, timetables and ICS; 0006/0007 |
| [0009](0009-compose-and-bff-trust-boundary.md) | Two Compose files and proxy trust |

ADR numbers identify decisions, not migrations. The migration head is `0007_timetable`;
there is no Alembic revision 0008. See [the inventory](../database.md#migrations).

## What is an ADR?

An ADR records:
- The context and problem behind a decision.
- The options considered.
- The decision made.
- The consequences and trade-offs.

## Naming convention

Use sequential numbers and descriptive names:

`0001-short-description.md`

## When to create an ADR

Create an ADR when a decision significantly affects the architecture, security, maintainability, deployment or future development of the project.

Small implementation details do not require an ADR.

## Status

Each ADR should indicate its status, such as `Proposed`, `Accepted`, `Deprecated` or `Superseded`.
