# Contributing to Sophikron

Thank you for your interest in contributing to Sophikron.

## How to contribute

1. Check existing issues before reporting a bug or proposing a feature.
2. Open an issue to discuss significant changes before implementing them.
3. Keep changes focused and avoid unrelated modifications.
4. Follow the project conventions documented in `AGENTS.md`.
5. Add or update tests when changing application behavior.
6. Update documentation when necessary.

## Pull requests

A pull request should:

- Explain the purpose of the changes.
- Describe the main implementation choices.
- Include tests or explain why they are not applicable.
- Pass the relevant tests, linting and build checks.
- Contain no secrets, credentials or unrelated generated files.

Use the pull request template provided in `.github/PULL_REQUEST_TEMPLATE.md`.

## Code quality

- Prefer simple, readable and maintainable code.
- Document functions and methods in English.
- Follow the formatting and linting rules configured for each component.
- Validate user input and enforce authorization on the backend.
- Treat user-provided JavaScript as untrusted code.

## Verification before a release

Use the Python interpreter configured for the project and the existing package scripts.
From `backend/`:

```sh
python -m pytest -q
ruff check . ../script
python run_tests.py
```

The first command skips PostgreSQL integration tests unless a dedicated test database is configured.
The existing `run_tests.py` launcher runs the complete suite, including migration rollback,
reapplication and SQLAlchemy metadata comparison, in a disposable Docker Compose project with
synthetic secrets. Docker Desktop must be running. It reuses the project Compose files, keeps the
development `.env` and persistent database untouched, and removes only its own test services and
volumes. See [database verification](docs/database.md#verification) for configuration and manual subsets.

From `frontend/`:

```sh
npm test
npm run check
npm run lint
npm run build
node --test tests/timetable-browser.mjs
```

On Windows PowerShell, use `npm.cmd` when the execution policy blocks `npm.ps1`.
The TypeScript test runner requires Node 22.6 or newer; Node 24 is also supported.
The timetable browser scenario uses the built frontend and a synthetic HTTP backend. It checks
calendar management, event editing, recurrence confirmations, staff availability and mobile access.
It complements the PostgreSQL authorization tests. Playwright needs an installed browser; no browser
is downloaded automatically.

For the real BFF journey, set `BFF_INTEGRATION=1` before running `python run_tests.py`.
Add `BFF_BROWSER_INTEGRATION=1` for desktop/mobile UI checks. The default channel is installed Edge;
`BFF_BROWSER_CHANNEL` selects another installed channel. `BROWSER_EXECUTABLE` selects the executable
for the native form regression in `npm test`, which otherwise skips if no compatible browser exists.
`BFF_SCREENSHOTS_DIRECTORY` optionally captures the synthetic overview. Use only synthetic test data
for these captures. The real BFF journeys refuse targets outside the disposable test environment.

Report the commands run, their actual results, skipped checks and remaining limitations. Passing
checks alone does not establish production readiness or comprehensive security.

## Documentation ownership

Keep each operational subject in one reference and link to it from related feature documents:

| Subject | Reference |
| --- | --- |
| Verification commands and release checks | This document |
| PostgreSQL, migration history and database operations | [database.md](docs/database.md) |
| Annual timetables, audiences, diagnostics and ICS | [timetable.md](docs/timetable.md) |
| Local demo scenario and API-only seeding | [timetable demo data](docs/timetable.md#local-demo-data) |
| Identities, sessions, keys and account recovery | [authentication.md](docs/authentication.md) |
| Accounts, promotion partitions and activity journal | [administration.md](docs/administration.md) |
| Subjects and public site configuration | [administration.md](docs/administration.md) |
| Frontend/BFF boundaries and deployment | [frontend-bff.md](docs/frontend-bff.md) |
| Course content and private files | [lessons.md](docs/lessons.md) |
| Pedagogical statistics | [statistics.md](docs/statistics.md) |

Keep `/docs` focused on architecture, component contracts and deployment design, written in English.
Keep contribution and release verification instructions in this root-level guide.
Do not add temporary security reviews, audit reports or implementation diaries to `/docs`.

## Button design contract

Use the shared rules in `frontend/src/app.css`; do not introduce local button palettes, borders,
hover effects or shadows. The three variants are filled primary (`button is-primary`), secondary
(`button`, optionally `is-light`), and quiet (`button is-text`). Icon-only controls use the shared
`icon-button` geometry; navigation and selection controls use the quiet variant.
Secondary and icon controls use a subtle gradient and thin tinted border. The shared `--action-tone`
drives both resting and hover gradients, including warning/danger tones; never hard-code a primary
hover for semantic actions. Filled primary actions remain solid and graph legends remain borderless.
Warning (`button is-warning`) and danger (`button is-danger`) are semantic tones with the same
geometry, motion and focus rules. Every danger action must open a confirmation first, or be the
explicit confirmation button inside an already-open dialog/panel. Informational warning controls
must not use danger styling. Retain disabled/loading states, accessible labels and reduced-motion
support. Check text contrast at rest and on hover in light and dark themes.
Chart visibility legends use the dedicated borderless soft-background `chart-toggle` variant;
keep it independent of pressed-button primary styling. Subject/promotion cards use neutral surfaces
with subtle assigned-color tints, a bounded subject emblem or promotion swatch, and neutral readable
labels. Emblems use an automatically contrasting foreground. Semantic warning and danger
tones take precedence over the secondary `is-light` treatment.

## Licensing

By contributing, you agree that your contributions will be distributed under the project's GNU General Public License v3.0, in accordance with the license terms.

## Questions

Use GitHub Discussions for questions and general discussions, when available. Use issues for bug reports and feature requests.

For builds containing local commits or uncommitted changes, use the [revision-aware build script](docs/database.md#building-images-with-revision-metadata). A modified build is labelled explicitly in the dashboard.
