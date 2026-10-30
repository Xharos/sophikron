# Sophikron

**An open-source platform for educational resources and interactive learning.**

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

- Create structured courses with documents, teacher collaboration and scheduled student access.
- Manage student and staff accounts, roles and promotions.
- Organize student groups and export attendance sheets.
- Plan timetables and oral examinations, with personal calendar subscriptions.
- Monitor account activity and educational resource usage.

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

After cloning the repository, run commands from its root. Install Docker with Linux containers
and Compose v2. The revision-aware build also requires Git and Windows PowerShell 5.1+ (or
PowerShell 7 on Linux). No host Python or Node installation is needed to run the Docker stack.

1. **Create the local configuration**, only for a new installation. Preserve any existing `.env`.

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   Linux shell:

   ```sh
   cp -n .env.example .env
   ```

2. **Edit `.env`**: set `SOPHIKRON_SECRETS_DIRECTORY` to an absolute private directory outside
   the repository. Leave `SOPHIKRON_ORIGIN=` empty for localhost, keep the default ports unless
   they are occupied, and leave SMTP disabled. See the [configuration variable reference](docs/environment.md)
   for every setting, expected values, secret files and how changes take effect.
3. **Create all six secret files** using the [Windows](docs/database.md#windows-powershell) or
   [Linux](docs/database.md#linux-shell) instructions, then [generate the identity keyring](docs/database.md#generate-the-identity-keyring).
   These instructions generate independent passwords and an empty SMTP password file; secrets
   never belong in `.env`. Keep the files for subsequent starts.
4. **Validate the configuration and start locally**:

   ```powershell
   docker compose -f compose.yaml -f compose.local.yaml config --quiet
   ./build.ps1 -Local -Start
   ```

   On Linux with PowerShell: `pwsh -File build.ps1 -Local -Start`.
   Without PowerShell, use the existing Compose files directly:

   ```sh
   docker compose -f compose.yaml -f compose.local.yaml up -d --build --wait
   ```

   Direct Compose builds show an unknown source revision. The application version still appears.
   Omit `-Start` from the script to build only. See [build options](docs/database.md#building-images-with-revision-metadata).

Open [the application](http://localhost:3000/login), sign in with `setup_operator` and the bootstrap
password, then complete `/setup` to create the permanent administrator. API docs are available at
[localhost:8000/docs](http://localhost:8000/docs). The directory name is arbitrary; keep the same
Compose project name and secrets between starts to reuse your data.

Stop with `docker compose -f compose.yaml -f compose.local.yaml down`; volumes are preserved.
For manual trials, [generate synthetic demo data](script/README.md) after completing setup.
For automated tests, follow the [development prerequisites](backend/README.md) and the
[release verification commands](CONTRIBUTING.md#verification-before-a-release):

```sh
cd backend
python run_tests.py
```

This runner creates its own secrets, random ports and disposable database; it preserves the local
installation. Frontend checks and optional browser journeys are described in the contribution guide.

See [setup, secrets and migrations](docs/database.md), [authentication and recovery](docs/authentication.md),
[release checks](CONTRIBUTING.md#verification-before-a-release), and the [documentation index](docs/README.md).
Production uses only `compose.yaml` and additionally needs [HTTPS proxy configuration](docs/frontend-bff.md#production-topology),
a public origin and backups. Do not use the local overlay in production.

## Contributing

Local test datasets can be generated with `script/seed_demo_data.py`; its central configuration
controls cohort sizes, staff, groups and annual timetables. See the [demo data guide](script/README.md)
for dry runs and separate test scenarios.

Contributions are welcome. Please read the [contribution guidelines](CONTRIBUTING.md) before submitting a pull
request.

Bug reports and feature requests can be submitted through GitHub Issues.

## License

Sophikron is free software distributed under the
[GNU General Public License v3.0](LICENSE).

---

_Built for teachers, by contributors to open education._
