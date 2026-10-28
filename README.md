# Sophikron

**An open-source platform for educational resources and interactive learning.**

Share teaching materials, publish educational pages and create interactive content.

Private timetables at `/timetable` provide annual calendars, live diffusion, recurring dated events,
full-screen group/student previews, custom option groups, lunch checks, annual hour totals and administrator-only archives.
Rooms and academic-year labels have a shared catalogue; daily rules belong to each calendar. The
permanent `prof` agenda provides independent annual availability and teaching-calendar overlays.
Members generate a personal calendar subscription from
`/me`; students use subscriptions without access to the timetable web interface. See
[timetable documentation](docs/timetable.md) for migrations, automatic September archival, permissions and setup.

<p align="center">
  <img src="https://github.com/Xharos/sophikron/actions/workflows/ci.yml/badge.svg" alt="CI" />
  <img src="https://img.shields.io/badge/SvelteKit-FF3E00?logo=svelte&logoColor=white" alt="SvelteKit" />
  <img src="https://img.shields.io/badge/Svelte-FF3E00?logo=svelte&logoColor=white" alt="Svelte" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Bulma-00D1B2?logo=bulma&logoColor=white" alt="Bulma" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker" />
</p>

## Features

- 📚 Share educational resources, including PDFs.
- 🧩 Create interactive educational pages.
- 🌐 Publish public or private content.
- 🤝 Reuse and share resources with other teachers.

## Technology stack

- **Frontend:** SvelteKit, Bulma and TypeScript
- **Backend:** FastAPI and Python
- **Database:** PostgreSQL
- **Containerization:** Docker

## Project structure

- `frontend/` — SvelteKit application
- `backend/` — FastAPI application
- `docs/` — Project documentation
- `infra/` — Infrastructure configuration

## Getting started

See [database documentation](docs/database.md) and [authentication documentation](docs/authentication.md) for detailed configuration and administration.

## Local setup

Administrators configure the public site name, welcome text and annual timelines in
`/dashboard?tab=configuration`. Settings are stored in PostgreSQL and take effect without a restart.
See [site administration](docs/site-administration.md) for subject and course access rules.

1. Create a `.env` file at the project root. Docker Compose automatically loads it for variable substitution. Configure the database, authentication settings, ports, and `SOPHIKRON_SECRETS_DIRECTORY` (see [.env.example](.env.example)).

2. Create the directory specified by `SOPHIKRON_SECRETS_DIRECTORY` and add the following files:

    - `bootstrap_password`
    - `db_admin_password`
    - `db_app_password`
    - `db_migration_password`
    - `smtp_password` (may be empty when SMTP is disabled)
    - `identity_keys.json` (generated below)

        Generate the identity keys from the `backend/` directory:

        ```bash
        python -m app.cli generate-keys --output "/path/to/secrets/identity_keys.json"
        ```

3. Build and start the local infrastructure:

    ```bash
    docker compose -f compose.yaml -f compose.local.yaml up -d --build
    ```

Access the [frontend](http://localhost:3000), [Swagger UI](http://localhost:8000/docs), and [ReDoc](http://localhost:8000/redoc) (using the configured ports).

### Stopping the infrastructure

Stop containers while **preserving PostgreSQL data**:

```bash
docker compose -f compose.yaml -f compose.local.yaml down
```

Stop containers and **delete Docker volumes, including PostgreSQL data**:

```bash
docker compose -f compose.yaml -f compose.local.yaml down -v
```

**Warning:** `down -v` permanently deletes data stored in Compose-managed volumes. Existing volumes are never automatically reset during startup.

## Getting started

See [PostgreSQL setup and development](docs/database.md) for Docker Compose startup, runtime secrets,
database roles, migrations and isolated integration tests. Existing PostgreSQL volumes are never
automatically reset or reprovisioned.

See [backend authentication](docs/authentication.md) for identity encryption keys, initial
administrator setup, invitations, cookie sessions and the versioned API. Generate the identity
keyring before starting the backend. See [backend administration](docs/administration.md) for
generated usernames, promotions, interactive name/username search, scoped teacher access and activity
events. The [responsive frontend dashboard](docs/frontend-bff.md) provides account/promotion management,
archiving, invitations and administrator statistics at `/dashboard`.
The [statistics dashboard](docs/statistics.md) adds interactive login/download charts, document
storage and scoped author/course analytics. For an existing local schema at 0005, its additive
upgrade command installs the new counters without resetting application data.
Complete school profiles add encrypted birth/contact/location information, baccalaureate subjects
and marks, orientation and an adult reference contact. Administrators edit profile fields; teachers
can update only the orientation project of students in their assigned promotions.

Use the single `compose.yaml` with a private `.env` for configuration. Local development, initial
administrator setup and isolated PostgreSQL verification use the same services.
After configuring secrets, `docker compose up -d --build` runs migrations and starts the application.
Complete the first administrator through `/api/v1/auth/setup`; SMTP is not required for this step.

Interactive courses support named private documents, inherited availability, staff-only sections,
YouTube players and tables with free column titles and optional cells. Documents persist in the
`documents_data` volume. Trusted course editors upload files without antivirus scanning; size,
format, quota and access checks remain enforced. See the
[document operations guide](docs/lesson-documents.md) for quotas, deletion, backups and verification.
See the [security audit](docs/security-audit.md) for verified controls and remaining risks.
The authorized amendment of migration `0005_lessons` is for the fresh baseline; installations
already at 0005 need a separate schema transition before running the updated application.

## Contributing

Contributions are welcome. Please read the [contribution guidelines](docs/CONTRIBUTING.md) before submitting a pull
request.

Bug reports and feature requests can be submitted through GitHub Issues.

## License

Sophikron is free software distributed under the
[GNU General Public License v3.0](LICENSE).

---

_Built for teachers, by contributors to open education._
