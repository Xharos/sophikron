# Sophikron frontend

SvelteKit, Svelte 5, TypeScript and Bulma, using the Node adapter and a server-side FastAPI BFF.
See [frontend architecture and deployment](../docs/frontend-bff.md) for existing Compose configuration,
origin/cookie protection and disposable end-to-end verification. No browser API secrets are needed.

## Development

Install the lockfile dependencies with `npm ci`. Start the existing backend stack as documented in
the root README. From this directory, set the process environment to
`ORIGIN=http://localhost:3000` and `BACKEND_ORIGIN=http://127.0.0.1:8000`, then run:

```sh
npm run dev -- --port 3000
```

Use `npm.cmd` on Windows if PowerShell blocks npm's script wrapper. Do not start the native frontend
on a port already occupied by the Compose frontend. Production uses the existing Docker frontend
and HTTPS host proxy; configuration remains in the existing root files.

## Establishment name

Set `ESTABLISHMENT_NAME=Sophikron` in the existing root `.env` file. Compose passes it only to
the frontend at runtime. The name appears in navigation, page titles, metadata, dialogs and the
footer. Missing, empty or whitespace-only values fall back to `Sophikron`; surrounding whitespace
is removed. Names are rendered as escaped text, including accents, quotes and HTML characters.

After the initial code update and image build, changing the name requires recreating only the
frontend container, with no image rebuild:

```sh
docker compose up -d --no-deps frontend
```

For local HTTP development, use the existing overlay:

```sh
docker compose -f compose.yaml -f compose.local.yaml up -d --no-deps frontend
```

For native development, export `ESTABLISHMENT_NAME` in the frontend process environment before
running `npm run dev`; the root Compose `.env` is not automatically loaded by that command.
This setting assumes one establishment per deployment and does not change authentication or data isolation.

## Account workspace

- `/setup`: first permanent administrator, names/email/password, generated immutable username.
- `/me`: own identity, promotions, activity and password change.
- `/dashboard`: administrator overview, account search/management and promotion rosters, or a
  teacher's scoped read-only directory including archived students.
- `/activate`: first activation or password renewal from an expiring invitation.
- `/dashboard/user?id=…`: complete encrypted school profile; administrator edits and scoped
  teacher orientation edits, with one save button and unsaved-navigation confirmation.

The dashboard switches sections in place and uses accessible dialogs/drawers for creation, editing
and account details. Desktop uses a sidebar; mobile uses horizontal navigation and stacked cards.
Account/promotion archiving preserves history; the backend rejects self-archiving. Invitations use
SMTP when configured, otherwise a displayed manual link. Future teaching statistics remain empty.

FastAPI enforces all permissions, membership scope and validation. Components share presentation and
interaction logic; `src/lib/server/dashboard.ts` translates allowlisted commands/resources to API
requests. Font Awesome Free solid icons are bundled locally (MIT code, CC BY 4.0 icons; retain notices).

## Verification

```sh
npm run check
npm run lint
npm test
npm run build
node --test tests/establishment.mjs
```

The unit suite uses Node's built-in runner (Node 22.6+ / 24). For real PostgreSQL + BFF integration,
run `python run_tests.py` from `backend/` with `BFF_INTEGRATION=1`. Add
`BFF_BROWSER_INTEGRATION=1` for Playwright desktop/mobile interactions using installed Edge, or
select an installed browser via `BFF_BROWSER_CHANNEL`. Playwright is a development-only Apache-2.0
dependency; no browser binary is downloaded automatically. All journeys use disposable services and
synthetic identities; the runner preserves the development stack and local secrets.
