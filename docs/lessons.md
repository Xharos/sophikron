# Course pages

Authenticated permanent accounts see every course card at `/lessons`. Cards expose the title,
description, icon, subject-inherited color, responsible teacher and collaborators, never teaching content.
The catalogue has no search form. Its responsible teacher and collaborators use the shared role
badges grouped into a professor line and a khôlleur line. Teacher takes precedence over administrator
and khôlleur in course badges. Only the current responsible teacher appears, never an additional
historical creator. Only administrators receive links to account profiles. Cards use compact layouts.
The dedicated `/lessons/{id}` page opens in reading mode. Students can open it only through a
current membership in an active, authorized promotion whose inclusive access dates include today.
Teachers and administrators can read all pages; responsibility or collaboration plus an assigned active subject is required for teacher edits.
Anonymous visitors are redirected to login. Pages are private, `no-store` and excluded from indexing.

## Editing and current permissions

Creation requires `teacher.access` and an assigned active subject. `users.manage` permits administrators to edit every course,
including recovering pages whose creator has lost their teaching role. An administrator without
`teacher.access` cannot create courses. Existing permissions remain explicit; no role inheritance is added.

Responsible-teacher and collaborator grants are references to accounts, not permanent editing capabilities.
Every mutation revalidates the session, active status, current permissions and collaboration inside
the transaction. A creator/collaborator losing their teacher role immediately loses teacher editing
rights, including with an existing session. An administrator retains their independent override.
Revoking a teacher role or archiving an account deletes subject assignments and collaborations.
Removing a subject deletes collaborations in that subject. Restoring a role does not restore them. Disabled accounts cannot authenticate. The bootstrap cannot use course APIs.

The eligible responsible teacher and administrators can add/remove collaborators. Collaborators
are active teachers assigned to the subject, or active khôlleurs with read-only full-content access.
The picker immediately offers five eligible accounts in stable ID order, then searches from the
first letter with a short debounce and cancellation of obsolete requests. Existing collaborators,
the historical creator and current responsible teacher are excluded server-side before the limit.
Each suggestion displays the person's name and pedagogical role badge. Adding or removing a
collaborator refreshes the suggestions. Browsing/searching uses the same management authorization.
Khôlleurs cannot edit or manage access. See [subject and role lifecycle](site-administration.md). Course editors can grant
or revoke any active promotion, independently of their personal promotion assignments. These actions
never change accounts, role assignments or promotion memberships.

Writes reuse the account lifecycle transaction lock so role/status changes cannot race an authorized
mutation. Course row locking and `expected_version` reject stale changes with 409. The editor saves
one coherent element or settings change at a time. Form drafts capture their original revision,
remain in memory on validation/conflict errors and are never stored in browser storage.

## Hierarchy and availability

Only sections can exist at the page root. Subsections must belong to sections. Text, YouTube,
file and table elements belong to a section or subsection. Table cells contain optional text,
YouTube or file elements addressed by row/column coordinates. Ordinary siblings are movable with buttons.
Element IDs remain stable on updates and moves. Removing a section/subsection removes its subtree
after confirmation. The API rejects cross-course element/parent IDs; composite foreign keys and a
PostgreSQL trigger also enforce hierarchy and immutable element parent/type/course fields.
Section blocks start with the author-entered title, without an automatic numbered label.
The outline continues linking to stable `#element-{id}` anchors for sections and subsections.

Only root sections can set `audience=staff`. Their entire subtree inherits that audience;
children cannot override it. Students receive neither private headings nor their resources.
All current teachers and administrators retain full reading access across courses; active collaborating
khôlleurs retain read-only full-content access. Historical authorship alone grants no capability.

Sections, subsections, text and tables are always available to authorized readers. Only files and
YouTube videos in student-visible sections can set a date rule:

- `inherit`: always available (the existing contract value is retained for compatibility).
- `from`: available from `starts_on` inclusively.
- `range`: available from `starts_on` through `ends_on`, both inclusive.

Unavailable resources retain their display title and file type in the student's programme, rendered
as muted, noninteractive cards without date/status labels. Video URLs are removed from student
responses outside the date window. Every download independently checks current course access,
section visibility and resource dates before opening the file. Staff can still read these resources.
Private sections have no date settings, including for their descendants. Switching a section to staff
clears descendant schedules; switching it back makes those resources always available by default.

Sections and subsections can be folded with keyboard-accessible heading buttons. Student sections
start folded; staff/edition sections start open. Outline links reveal the target and its ancestors.
Folding affects presentation only and never changes authorization or publication.

### Existing local databases

The authorized amendment is in the existing `0005_lessons` baseline, with no new revision. A fresh
installation receives the new constraints automatically. For an already applied baseline, back up
and run during maintenance using the existing migration service:

```sh
docker compose run --rm migrate python -m app.cli upgrade-lesson-policies
```

This idempotent, transactional helper clears structural dates and dates in private sections,
normalizes descendant visibility, installs the matching constraints and advances affected course
versions. Legacy individually private descendants make their entire section private, preserving
confidentiality. It neither drops content nor resets persistent volumes. Do not downgrade/recreate
the database to apply this amendment.

Dates are evaluated on each request using the Europe/Paris calendar, without scheduled jobs.
Promotion year `2026` defaults to September 1, 2026 through **August 31, 2027 inclusive**. The year-end
constants live in `app/services/lessons.py`. Editors can customize each grant's period; a promotion
with year 9999 requires an explicit representable period. Multiple memberships grant access if any
one currently qualifies. Archived promotions suspend access immediately; reactivation restores it
only if the membership, course grant and dates still qualify. Revoking a grant removes page access
while leaving the catalogue card visible. Promotion grants retain their stored dates if metadata changes.

## Text, videos and documents

The text language supports `*italic*`, `**bold**`, `==colored==` and combinations such as
`==***all three***==`. Exact paired delimiters are recognized; unmatched delimiters remain literal.
The editor has selection-formatting buttons and a live preview. Colored passages use the course's
hexadecimal color, with its displayed shade adjusted when necessary for at least 4.5:1 contrast on
the current light or dark application surface. The saved color stays unchanged. Text is rendered through normal
Svelte escaping, never raw HTML. Text elements are bounded to 3000 characters so even multibyte
Unicode remains compatible with the existing request-body limit.

YouTube URLs must use HTTPS and an exact allowed YouTube host. Video IDs are validated and URLs
are canonicalized, with no server-side remote fetches or accepted iframe markup. Videos open as
an embedded privacy-enhanced player after an explicit click. Its iframe sends only the site origin
as referrer, using `strict-origin-when-cross-origin` locally; the global policy stays unchanged.
No thumbnail or iframe contacts YouTube before activation. The embedded player provides access
to YouTube; no separate external link is displayed below it.

Document display titles are author-selected and editable independently of original filenames.
The page uses compact square tiles with local Font Awesome SVG icons for each accepted type;
clicking downloads the file. The display title appears below, without the matching file extension,
and is truncated visually when necessary; the full label remains available on hover and to assistive technology.
JPEG/PNG are limited to 10 MiB, PDF/DOCX/XLSX to 25 MiB, ZIP to 50 MiB and Python source to 1 MiB.
Legacy DOC/XLS, macros, encrypted/uninspectable files and nested ZIP archives are not accepted.
Python files are downloaded, never executed. Oversized PDF selection offers an optional iLovePDF
link without automatically transmitting the document. File limits come from the authenticated API.

Tables support 1–20 rows and 1–6 columns with arbitrary, editable titles. No semantic columns
such as student answer/teacher correction are encoded in SQL. Empty cells have no resource record.
Each populated cell has its own title, dates and audience; dates inherit through the table unless
explicitly replaced. Removing rows/columns requires UI confirmation, removes their resources and
shifts remaining coordinates. Staff restrictions always propagate even when a child overrides dates.
The page does not implement personal student submissions.
Tables keep their columns on desktop and mobile, with a Bulma scroll container when they exceed
the available width. The container can be focused to scroll with the keyboard.

The [historical resource audit](lesson-resources-audit.md) records the earlier design discussion;
the behavior in this document and the [storage operations guide](lesson-documents.md) is authoritative.

## API and audit journal

The authenticated `/api/v1/lessons` module exposes a bounded searchable catalogue, course creation,
detail and metadata updates, element create/update/delete/move, collaborator add/remove, promotion
grant/update/revoke, and authorized active-promotion/teacher options. Mutation bodies require
`expected_version` except creation. The existing exact-origin and CSRF header rules apply. Request
bytes and body-read time are bounded by the shared middleware. Teacher search queries are omitted
from API access logs. Options never expose student rosters, email or school-profile data.

The SvelteKit BFF uses an explicit command/resource allowlist at `/lessons/command` and
`/lessons/options`. Browser requests cannot choose arbitrary backend paths or HTTP methods.
Binary endpoints use separate BFF routes `/lessons/upload` (POST) and `/lessons/download` (GET).
The backend first reserves a single-use upload via `POST /api/v1/lessons/{id}/uploads`, then
accepts a raw octet stream at `PUT /api/v1/lessons/{id}/uploads/{key}`. No base64 or multipart
encoding is used. Download is `GET /api/v1/lessons/{id}/files/{file_id}`. Every download rechecks
live course access, audience and dates, and verifies stored size and SHA-256 before streaming.
Binary routes retain origin/CSRF/session controls. Only the exact upload route bypasses small JSON
body buffering; the browser, BFF and backend enforce independent file limits.

`POST /api/v1/lessons/{id}/elements/{element_id}/table` adds/removes rows/columns and renames
columns using an explicit action, coordinate, optional label and `expected_version`.
`DELETE /api/v1/lessons/{id}` is restricted to the eligible responsible teacher or administrator,
requires the current version, journals deletion and queues all file removals through SQL cascades.

Successful course, element, collaborator and promotion changes record `lesson.*` events atomically.
They reference the course and relevant participant/element/promotion; audit metadata includes changed
field names, availability before/after, movement direction and removed-subtree size. Text bodies,
video URLs and private account fields are not copied into the journal. Historical actor/subject
roles follow the existing event model. The administrator journal resolves the current course title,
renders a clickable course tag and links to retained elements by anchor. Deleted-element events
link to the course. This journal does not provide revision restoration or collaborative live editing.

## Migration and verification

`0005_lessons` creates courses, content, responsibility and access associations on the authorized
fresh-database baseline. It follows authentication, configuration, promotions and subjects, each in
its own feature revision. Khôlleur roles and the journal belong to authentication.
Apply through the existing migration service or `alembic upgrade head` using the migration role.
At the user's explicit request, document/table/audience additions amend `0005_lessons` itself.
An installation already stamped `0005_lessons` will not acquire these changes through `upgrade head`.
Do not reset or downgrade a populated installation: arrange a separate reviewed schema transition.
This implementation has not modified a development or production database. The downgrade refuses
to discard file metadata or outstanding deletion jobs; remove files and drain cleanup first.
No development database migration or persistent-data reset is performed by automated tests.

Run `python -m pytest -q` and `ruff check .` from `backend/`. `python run_tests.py` provisions the
existing disposable Docker test stack and additionally exercises actual PostgreSQL constraints,
role revocation, promotion access, inherited dates and migration roundtrips. Set `BFF_INTEGRATION=1`
and optionally `BFF_BROWSER_INTEGRATION=1` to include HTTP and desktop/mobile browser journeys.
From `frontend/`, run `npm test`, `npm run check`, `npm run lint` and `npm run build`.
