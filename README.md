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

See [PostgreSQL setup and development](docs/database.md) for Docker Compose startup, runtime secrets,
database roles, migrations and isolated integration tests. Existing PostgreSQL volumes are never
automatically reset or reprovisioned.

See [backend authentication](docs/authentication.md) for identity encryption keys, initial
administrator setup, invitations, cookie sessions and the versioned API. Generate the identity
keyring before starting the backend. The authentication UI is not implemented yet.

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
