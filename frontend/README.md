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

Administrators edit the name in `/dashboard?tab=configuration`. The frontend reads the public
`GET /api/v1/site` contract on each server load; no environment variable or restart is required.
The name appears in navigation, titles, metadata, dialogs and the footer and is always escaped.
The same page configures the public welcome text and multiple annual timelines. See
[site administration](../docs/site-administration.md) for subjects, collaboration and revocation.

## Account workspace

The footer offers Light / Device / Dark appearance controls, defaulting to the device's preference.
The `sophikron_theme` cookie stores `light`, `system` or `dark` for one year in this browser,
independently of login. System mode follows live operating system/browser changes through CSS;
it never stores the resolved theme. The server reads the allowlisted cookie before rendering HTML
to avoid a flash of the wrong theme. No database migration or account preference is involved.
The cookie is intentionally readable by JavaScript, contains no identity data, uses `SameSite=Lax`
and `Path=/`, and adds `Secure` on HTTPS. If cookies are blocked, changes apply to the current page.

Shared colors live in `src/app.css` as paired `light-dark()` tokens (modern browsers supporting this
color function). Components should reuse these tokens, including for muted surfaces and status
badges, rather than literal white backgrounds. Colored text and charts adjust displayed shades for
contrast; solid colored icons use contrasting black/white foregrounds without changing saved colors.

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
SMTP when configured, otherwise a displayed manual link. Teachers can inspect statistics for their
own creations and open affiliated course statistics directly from the course page.
Promotion member selection offers pupils and teaching staff. Teaching staff use the backend's
`role=teaching` union of Teacher and Khôlleur roles, with one shared result limit and no duplicates.
Promotion member lists offer All roles, Pupils and Professors; Professors uses this same union with
server pagination. Account creation and assignment forms exclude administrator-only accounts.
Losing the last eligible role automatically removes active and archived promotion memberships;
the role confirmation explains this and the journal records each automatic removal.

FastAPI enforces all permissions, membership scope and validation. Components share presentation and
interaction logic; `src/lib/server/dashboard.ts` translates allowlisted commands/resources to API
requests. Font Awesome Free solid icons are bundled locally (MIT code, CC BY 4.0 icons; retain notices).

## Statistics

The administrator overview and scoped teacher/course panels share SVG charts and design tokens.
See [statistics](../docs/statistics.md) for counting rules, permissions, storage measurements and
the additive upgrade command for an existing local database.

## Missing pages

The shared error page renders a dedicated design only for HTTP 404, with the local animated
`src/lib/assets/lost-cat.svg` and one of three hardcoded French messages chosen on client mount.
The cat lowers its right forepaw while looking at the visitor and the broken sign; the animation
loops every twelve seconds and respects `prefers-reduced-motion`. Other error statuses retain
their existing message and presentation. The HTTP status and backend behavior are unchanged.

## Verification

```sh
npm run check
npm run lint
npm test
npm run build
node --test tests/visual-picker.mjs
node --test tests/establishment.mjs
```

The visual picker/theme browser tests require Playwright Chromium. Set `PLAYWRIGHT_CHANNEL=msedge`
to use an installed Microsoft Edge instead.

The unit suite uses Node's built-in runner (Node 22.6+ / 24). For real PostgreSQL + BFF integration,
run `python run_tests.py` from `backend/` with `BFF_INTEGRATION=1`. Add
`BFF_BROWSER_INTEGRATION=1` for Playwright desktop/mobile interactions using installed Edge, or
select an installed browser via `BFF_BROWSER_CHANNEL`. Playwright is a development-only Apache-2.0
dependency; no browser binary is downloaded automatically. All journeys use disposable services and
synthetic identities; the runner preserves the development stack and local secrets.
