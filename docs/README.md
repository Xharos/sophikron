# Architecture documentation

This directory documents the application architecture, component contracts and deployment design in English.
Contribution and release verification instructions belong in [CONTRIBUTING.md](../CONTRIBUTING.md).
Temporary reviews, audit reports and implementation diaries do not belong here.

Start with [local installation, secrets and migrations](database.md). The root
[Getting started](../README.md#getting-started) gives the shortest path to a working test instance.
Use synthetic data locally; the [demo guide](../script/README.md) describes API-only seeding.

| Reference | Contents |
| --- | --- |
| [Environment configuration](environment.md) | Variable reference, defaults, secret provisioning and Compose overrides |
| [Database and setup](database.md) | Docker, six secrets, startup, roles, migrations and isolated tests |
| [Authentication](authentication.md) | Identities, sessions, setup, invitations, recovery and key rotation |
| [Administration](administration.md) | Accounts, promotions, subjects, public settings, course responsibility, journal and versions |
| [Frontend/BFF](frontend-bff.md) | Pages, cookies, same-origin requests, proxy trust and HTTPS deployment |
| [Courses and documents](lessons.md) | Content trees, inherited access, private files, quotas, cleanup and backup/restore |
| [Timetables](timetable.md) | Audiences, annual settings, publication, diagnostics and ICS |
| [Statistics](statistics.md) | Pedagogical indicators, storage and API monitoring |
| [Architecture decisions](decisions/README.md) | Why schema and deployment boundaries were chosen |

Subject/site operations are consolidated into administration; document operations into courses.

See also [building images with revision metadata](database.md#building-images-with-revision-metadata).
