# ADR 0011: Shared curricula, competency graphs and portable subject files

- **Status:** Accepted
- **Date:** 2026-11-13
- **Sources:** [migration](../../backend/alembic/versions/0009_curricula.py),
  [service](../../backend/app/services/curricula.py), [JSON contracts](../../backend/app/schemas/curricula.py).
- **Extends:** [ADR 0006](0006-teaching-catalogues-and-courses.md),
  [ADR 0009](0009-compose-and-bff-trust-boundary.md).

## Context and decision

CPGE programmes describe competencies across two years, sometimes with several hierarchical
levels and shared descendants. Other subjects need a simpler structure. Teachers enter the current
official programme; the application does not enforce a particular ministry document structure.

Represent the pathway and reference programme by one `curricula` entity with administrator-selected
existing subjects. Promotions may reference a curriculum, but their free names, years and calendar
identities remain independent. Keep an optional external official PDF link without server-side
fetching or uploading. Updates take effect immediately; do not introduce draft publication or
historical official-programme editions in this feature.

Store competencies as a subject-scoped directed acyclic graph, not a recursive JSON tree. Composite
foreign keys constrain both link endpoints to the same curriculum and subject. Allow several parents
without duplicating the competency or its notes. Services reject cycles iteratively under a curriculum
row lock. Deleting a competency removes its links and preserves its children.

Generate one code per identity from the first shortest ordered path. Alternate uppercase letters,
numbers and lowercase letters (`A`, `A.1`, `A.1.a`, `A.1.a.1`); recompute after detachments and edits.
Codes are derived response fields, not editable database columns. Keep `position` for sibling order
and nullable colors for branch inheritance.

Grant all permanent administrators, teachers and kholleurs reading access through `curricula.read`.
Metadata management requires `curricula.manage`; competency writes require either that capability
or `curricula.edit` plus a current assignment to an active subject. Services recheck live permissions
and serialize with the existing account/assignment lifecycle lock. UI visibility is not authorization.

Keep `curricula.version`: it is an optimistic concurrency counter used by metadata, graph edits,
imports and undo, not an official programme edition. Persist at most twenty inverse operations per
actor/curriculum in JSONB. Undo rechecks current subject rights and the exact intervening revision;
it restores identities/links or removes one imported batch atomically. Old node IDs in undo have no
competency foreign key because deleted identities must be restorable; batch records use a sentinel
and explicit created IDs. Journal successful changes with bounded human-readable references.

Use versioned JSON files per subject: a flat node list with file-local IDs and parent IDs preserves
shared descendants. Import appends with fresh identities, retains existing data, and can be undone
as one action. Export names the download after its subject using a safe portable basename. The server
validates the original JSON text, rejects ambiguous/unknown fields, invalid links, cycles and excessive
size/depth, and never evaluates file content. Existing CSRF/session controls and narrow bounded-body
exceptions remain in force; do not raise the ordinary request limit globally.

Use Three.js for the desktop graph and existing HTML controls, modals, subject badges and file
dropzone. Recalculate visible branches on concentric rings when nodes open/close. Direct clipped
links and particles connect block borders. A compact indented outline is always available, and is
the only view at widths up to 650 px; no WebGL context is created there. Renderer resources are
released when switching to mobile and recreated on returning to desktop. Keep this layout independent
from persisted pedagogical data.

## Consequences and alternatives

A single parent column would be simpler but could not express shared competencies. Persisting one
recursive JSON document would weaken relational integrity and complicate scoped edits. Persisted
manual codes would drift after graph changes. Version-free writes would overwrite concurrent edits
and make inverse operations unsafe. Server-side programme PDF fetching is unnecessary for a link and
would introduce an additional network trust boundary.

The graph has one canonical displayed identity for shared nodes; extra cross-links can still cross.
Undo is short operational recovery, not programme versioning or a full audit snapshot. Reimporting
the same file appends duplicates by design. Limits and current API/UI behavior are documented in
[curricula](../curricula.md), including migration compatibility and downgrade behavior.
Verification covers the Alembic chain, repeated upgrade/downgrade,
schema/metadata equivalence, existing-row preservation, authorization, revisions, codes, file
validation and browser desktop/mobile interactions.
