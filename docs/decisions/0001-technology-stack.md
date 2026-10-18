# ADR 0001: Technology Stack

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

Sophikron is an open-source educational platform designed to let teachers share educational resources, including PDFs, and create interactive educational pages.

The platform must support a modern user interface, a maintainable backend API, persistent data storage and future deployment through containers.

## Decision

The project uses the following technologies:

- **SvelteKit** for the frontend application.
- **TypeScript** for type-safe frontend development.
- **FastAPI** for the backend HTTP API.
- **Python** for backend implementation.
- **PostgreSQL** as the relational database.
- **Docker** for containerized development and deployment.

## Rationale

This stack separates the frontend, backend and database responsibilities.

SvelteKit and TypeScript provide a structured environment for building interactive interfaces. FastAPI provides a Python-based API framework with automatic API documentation. PostgreSQL provides relational data storage, while Docker helps make development and deployment environments reproducible.

## Consequences

- Frontend and backend can be developed and tested independently.
- API contracts must remain consistent between frontend and backend.
- Database schema changes must be managed carefully as the application evolves.
- Deployment configuration must account for each service and its dependencies.
- Interactive content supplied by users must be isolated and secured appropriately.

## Alternatives considered

Other frontend frameworks, backend frameworks and database systems could be used. The current stack was selected to provide a clear separation of responsibilities and a maintainable foundation for the project.
