# Curricula and competencies

A curriculum represents one pathway and its current official two-year programme, such as PTSI/PT.
Administrators create it at /curricula, select existing subjects, and supply a title, optional
description and HTTP(S) official PDF URL. The PDF remains external: the server does not fetch it.
There is no separate pathway catalogue or official-edition history. See [ADR 0011](decisions/0011-curricula-and-competency-graphs.md).

Promotions may reference a curriculum through nullable curriculum_id. Their free names, academic
years and timetable/calendar associations remain independent. Assigning a curriculum is optional.

## Storage and concurrency

| Store | Purpose and integrity |
| --- | --- |
| curricula | Title, description, source URL, active state and concurrency version |
| curriculum_subjects | Selected existing subjects; composite curriculum/subject key |
| competencies | One identity with name, optional semester 1-4, knowledge, comment, color and position |
| competency_links | Directed parent/child links; both endpoints constrained to the same curriculum/subject |
| curriculum_undo | Bounded inverse operations keyed by actor and curriculum, with revision and payload |
| promotions.curriculum_id | Optional foreign key; the referenced curriculum cannot be deleted while linked |

The consolidated migration is 0009_curricula, following 0008_kholloscope. It creates the final schema
directly. There is no tracks table, track_id field or editable competency code column.

The version field is in active use: writes carry expected_version and return HTTP 409 when another
write has intervened. It is not an official programme edition. Metadata, competencies and imports
advance this curriculum-wide counter. Locks and live authorization checks serialize with account
and subject-assignment changes. A stale graph from another subject must be refreshed before editing.

The hierarchy is a DAG. Self-links, descendant-as-parent links and cross-subject/curriculum parents
are rejected. A shared competency remains one row and one displayed identity. Deleting a node
removes its edges, retaining all children; children with no remaining parent become roots. Removing
a subject from a curriculum is refused while it contains competencies. Archived subjects/curricula
remain readable but reject graph writes. Optional text is normalized to null when empty.

Automatic codes follow the first shortest path in sibling position/ID order. Root letters continue
beyond Z to AA; deeper segments alternate numbers and lowercase letters, for example A.1.a.1.
Each identity has one code even with several parents. Codes and display order are recomputed after
reparenting/deletion. Color is explicit or inherited from the canonical branch and subject.

## Roles and API

| Capability | Default grants | Effective scope |
| --- | --- | --- |
| curricula.read | admin, teacher, kholleur | All curriculum metadata and subject graphs, including export |
| curricula.edit | teacher | Competencies/import in currently assigned active subjects of active curricula |
| curricula.manage | admin | All metadata and active-subject graph editing/import |

Students, guests and bootstrap sessions cannot access this feature. Hidden buttons are convenience;
backend services always check current rights. Writes retain the existing session, Origin and CSRF
policy. API paths below are relative to /api/v1 and private responses use no-store caching.

| Method and path | Operation |
| --- | --- |
| GET /curricula/catalog | Curricula, selected subjects and effective editing flags |
| POST /curricula | Create administrator-owned metadata |
| PUT /curricula/{id} | Update metadata with expected_version |
| GET /curricula/{id}/subjects/{subject_id} | Read a complete subject graph and current revision |
| POST /curricula/{id}/subjects/{subject_id}/nodes | Create a competency and incoming parent links |
| PUT /curricula/{id}/subjects/{subject_id}/nodes/{node_id} | Replace fields and incoming links |
| DELETE /curricula/{id}/subjects/{subject_id}/nodes/{node_id} | Delete only that competency |
| POST /curricula/{id}/undo | Undo the actor's latest eligible operation |
| GET /curricula/{id}/subjects/{subject_id}/export | Downloadable portable subject document |
| POST /curricula/{id}/subjects/{subject_id}/import | Append a validated document atomically |

The SvelteKit page uses allowlisted POST commands through /curricula/data; file operations use
/curricula/transfer. Services, not routing/UI code, own permissions, graph mutations and transactions.
Metadata and ordinary node writes retain the 16 KiB default request guard. A programme link rejects
credentials and unsupported URL schemes and causes no server-side outbound request.

## JSON files

The download modal selects a subject. Its JSON contains all competencies, including collapsed ones,
with names, semesters, knowledge, comments, colors, positions and all parents. The filename is the
subject name plus .json, preserving accents and replacing control/path/reserved filename characters.
Windows device basenames are prefixed with an underscore. The portable format is:

```json
{"format":"sophikron.competencies","version":1,"subject_name":"SII","nodes":[
  {"id":1,"name":"Analyser","parent_ids":[],"semester":null,"knowledge":null,"comment":null,"color":"#4361EE","position":0},
  {"id":2,"name":"Analyser le besoin","parent_ids":[1],"semester":1,"knowledge":"Associated knowledge","comment":null,"color":null,"position":1}
]}
```

The document version describes the file format, independently of the curriculum concurrency version.
File IDs are local references: imports create fresh database IDs. Codes are regenerated, never trusted
from the file. An import adds to the chosen subject, without matching by name or replacing anything.
Importing the same file twice creates duplicate content. The whole batch is transactional and may
be undone as one action. A failed import changes neither nodes, revision nor history.

The modal reuses the document dropzone for one file, by drag/drop or file selection. The browser
checks extension, announced MIME type, byte size and format before previewing the count. It sends
the original JSON text so the server can detect duplicate keys. Server validation is authoritative:

- Maximum file size: 4 MiB; maximum subject size: 2,000 nodes including existing ones after import.
- Maximum file graph: 20,000 edges, 100 parents per node and 128 levels; field lengths match node editing.
- Reject unknown fields/format versions, duplicate or prototype-related keys, invalid colors/semesters,
  duplicate IDs/parents, missing parents, self-links and cycles. Cycle/depth checks use an iterative queue.
- Parse as JSON only. Never evaluate text or interpolate it as HTML. No uploaded file is written to disk.
- Only the exact backend import route and the BFF transfer route accept 8 MiB + 4 KiB request envelopes,
  allowing the original file text to be JSON-escaped. Other JSON routes keep their ordinary limits.

The import API expects expected_version and document (original JSON string, or an object for API
clients). Unsupported Content-Type is 415, invalid content is 422, oversized requests/exports are
413, and stale edits are 409. Export also refuses graphs beyond the exchange-format limits rather
than returning an unusable document. User-facing errors do not echo uploaded contents.

## Exploration and editing

The header links to /curricula only for authorized users. One curriculum is selected at a time.
Subjects retain their existing emblems/colors and can be hidden or isolated. Their graphs are fetched
on page entry so direct-child counts are available before expansion; counts exclude grandchildren.
Metadata and undo controls are icon buttons with accessible labels and tooltips.

Desktop uses Three.js with HTML labels. Visible depths form concentric rings around each subject;
opening/closing a branch recalculates angles and radii for all open branches. Actual rectangles and
visible descendant demand determine spacing. Hidden descendants reserve no space. Direct segments
connect clipped block borders; particles use the same segments. Shared cross-links can still cross.
Nodes shrink/desaturate slightly with depth, capped after three levels, while borders retain strong
branch color. Long labels are truncated in the graph but remain available in tooltips and dialogs.

Wheel zooms, dragging the background pans, dragging a node temporarily displaces it. Soft repulsion
and damped springs restore its anchor. Space or Recenter fits final visible anchors during expansion.
Search uses inherited colors and subject names to distinguish identical names; selecting a result
reveals and highlights its ancestor paths/links for ten seconds. Fullscreen toggles its label and
behavior and tracks browser-driven exits. Reduced motion disables drift/particles and background
rendering pauses when hidden or in the outline. GPU resources are released on leaving the graph.

At widths up to 650 px, only the compact text outline is available and no WebGL context is created.
Returning to desktop recreates the renderer/canvas. The outline lists descendants immediately below
their canonical parent, with indentation and parent-colored borders; shared identities appear once.
Clicking a subject title adds a root competency when permitted; readers see a non-editable title.

Editing uses one modal. Name is a single-line input and Enter saves. Semester is initially collapsed.
Relations contains parents and display position; Presentation contains only inherited/custom color
with synchronized native picker and HEX field. Add-child/delete actions sit left, cancel/save right,
wrapping on narrow screens. Delete confirmation retains its explicit child-preservation explanation.

## Undo and journal

Undo and Ctrl+Z (Cmd+Z on macOS) reverse eligible competency edits from the current page, including
one imported batch. Text fields keep native undo. At most twenty inverse operations per user and
curriculum are retained. Undo restores identities/relations, recalculates codes and rechecks current
subject rights and the exact revision. Any intervening write prevents unsafe reversal. Curriculum
metadata and navigation are outside this undo scope. History is operational recovery, not editions
of the official programme. Journal entries identify action, curriculum, subject, competency, changed
fields, relation counts or imported count without copying long teaching text.

## Migration compatibility and verification

Only a fresh database or the supported exact 0008 baseline can apply the consolidated 0009 directly.
Databases using earlier development schemas require an inspected transition, even when their feature rows are
empty. A reused 0009 revision ID can represent a different schema: upgrade head alone
cannot repair the old 0009 schema. Preserve backups and complete the old chain with its original code
before considering a schema-equivalence review and controlled version-table transition. Do not reset
or downgrade a valuable database to bypass this. No automatic transition/stamping is performed.
Downgrading consolidated 0009 to 0008 deletes curriculum data/history and promotion associations;
existing promotions, subjects and calendars survive. Published migrations become immutable.

Run the complete backend suite with backend/run_tests.py using the configured interpreter and Docker.
It uses the existing isolated Compose runner and synthetic secrets, with migration upgrade/downgrade,
metadata comparison, default grants, retained older rows, DAG constraints, rights, concurrency, codes,
JSON and undo tests. Never point migration tests at a valuable database.

From frontend/, run npm run check, npm run lint, npm test and npm run build. Browser verification is
node tests/curricula-browser.mjs (set PLAYWRIGHT_CHANNEL=chrome to use installed Chrome). It covers
expansion, zoom/pan, editing, text hierarchy, responsive mobile-only/no-WebGL behavior, fullscreen,
roles, color synchronization, JSON download filename, drag/drop, import and undo against synthetic
HTTP fixtures. Real API/database guarantees are covered separately by PostgreSQL tests.
