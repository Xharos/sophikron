# Sophikron

**An open-source platform for educational resources and interactive learning.**

Share teaching materials, publish educational pages and create interactive content.

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

The public establishment name is configured with `ESTABLISHMENT_NAME=Sophikron` in the root
`.env` file. It is read by the frontend at runtime and defaults to `Sophikron` when blank or absent.
See [frontend configuration](frontend/README.md#establishment-name) for container recreation
and native development instructions.

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
Complete school profiles add encrypted birth/contact/location information, baccalaureate subjects
and marks, orientation and an adult reference contact. Administrators edit profile fields; teachers
can update only the orientation project of students in their assigned promotions.

Use the single `compose.yaml` with a private `.env` for configuration. Local development, initial
administrator setup and isolated PostgreSQL verification use the same services.
After configuring secrets, `docker compose up -d --build` runs migrations and starts the application.
Complete the first administrator through `/api/v1/auth/setup`; SMTP is not required for this step.

## Contributing

Contributions are welcome. Please read the [contribution guidelines](docs/CONTRIBUTING.md) before submitting a pull
request.

Bug reports and feature requests can be submitted through GitHub Issues.

## License

Sophikron is free software distributed under the
[GNU General Public License v3.0](LICENSE).

---

*Built for teachers, by contributors to open education.*
