# ADR 0009: Two Compose files and an explicit BFF proxy boundary

- **Status:** Accepted
- **Date:** 2026-10-30
- **Sources:** `compose.yaml`, `compose.local.yaml`, `infra/postgres/init/001_roles.sql`,
  `infra/nginx.conf`, backend proxy middleware and frontend server helpers.

## Context and decision

Keep one deployment base and one explicit local overlay. Both reuse the existing PostgreSQL, migration,
API and frontend images. Preserve dedicated administrator/migrator/runtime database accounts and the
startup chain database health -> migration completion -> API health -> frontend.

The public `.env.example` documents non-secret settings; the private `.env` supplies substitutions.
Pass only an explicit allowlist with defaults, never the entire file. Mount six host secret files;
the API receives neither the administrator nor migration password. Provision roles only on empty volumes.

The base publishes only the loopback frontend for a host HTTPS proxy. That proxy replaces `X-Real-IP`;
the BFF replaces API forwarding headers. Uvicorn trusts only the fixed BFF network address. The local
overlay also publishes API/PostgreSQL on loopback, disables trusted browser forwarding headers and
permits HTTP cookies with exact local origins. It must never be used in production.

API, frontend and migration containers run with an init process, no Linux capabilities and
`no-new-privileges`. Their image filesystems are read-only. Each has an isolated 64 MiB `/tmp`
tmpfs with `noexec,nosuid,nodev`; temporary files are ephemeral and consume memory.
The API's `documents_data` volume remains writable for both staged uploads and published files.
Database writes use PostgreSQL's own writable volume. PostgreSQL retains its image's initialization
privileges and writable filesystem. All four services rotate Docker JSON logs at 10 MiB per file
with at most three files per container. These limits do not apply to application data volumes.

## Consequences and alternatives

Local setup requires only Docker, a private secret directory and `.env`; production additionally needs
TLS, proxy configuration, backups and host controls. Exposing the base frontend on all interfaces while
trusting a client-address header would let direct callers forge rate-limit identities, so loopback is
intentional. Fixed internal addresses require coordinated subnet overrides on conflicting hosts.
Separate full Compose stacks would duplicate wiring and drift; combining local HTTP settings into the
base would weaken deployment defaults. The existing test runner uses these same files with synthetic
secrets, dynamic ports and an independent project and removes only its disposable resources.
