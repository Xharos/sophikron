# Backend accounts, promotions and activity

The administrator dashboard API is available under `/api/v1/admin`; the responsive SvelteKit
workspace consumes it at `/dashboard`. Teachers use separate, scoped `/api/v1/teaching` routes.
All responses use `Cache-Control: no-store`. Mutations require the existing session cookie, trusted
origin and `X-CSRF-Protection: 1`; bodies must be JSON. Bootstrap sessions cannot use these routes.

## Account identities

Every autonomous entity uses a PostgreSQL `BIGINT` identity starting at 1. Each table has its own
sequence, which may have gaps after rollback. Associations use composite primary keys. IDs are JSON
numbers; clients must preserve integer precision if IDs ever exceed JavaScript's safe integer range.
Session and invitation credentials remain independent random secrets, never integer IDs.

`POST /admin/users` accepts:

```json
{
    "first_name": "Valentin",
    "last_name": "BURGAUD",
    "email": "valentin@example.org",
    "roles": ["user"],
    "promotion_ids": [1, 2]
}
```

Names are required, at most 100 characters, normalized to Unicode NFC and trimmed/collapsed spaces.
French letters, accents, ligatures, spaces, hyphens and straight/curly apostrophes are accepted.
Whitespace-only names, digits, other alphabets and unsupported punctuation are rejected. The
bootstrap account alone may omit names/email and use its explicitly configured username.

The server generates the username once: normalized first initial + first four normalized family-name
letters (or the complete shorter name) + a random suffix from 100 through 999. Accents, apostrophes,
hyphens and spaces disappear; `œ` becomes `oe`, `æ` becomes `ae`. Examples: `vburg103`, `vroy103`,
`vremi103`, `dduse103`. There are 900 suffixes per prefix. Each is tried at most once in random order;
exhaustion returns 409. The lifecycle transaction lock serializes generators across API workers;
the unique HMAC index remains the final database uniqueness control.

Supplying `username`, `password`, status or privileged flags returns 422. Profile updates let an
administrator edit names/email while preserving the original username. The first permanent administrator's
`POST /auth/setup` also requires `first_name`, `last_name`, `email`, `password`, with generated username.

All four identity fields are AES-256-GCM encrypted using the existing external keyring. The integer
account identity is reserved before encryption because ciphertext authentication binds to that row.
Exact username/email lookups retain their separate HMAC indexes. The CLI identity-key rotation
re-encrypts all identity and private school-profile fields. Never copy personal identities into activity JSON or application logs.

Account, roles, requested memberships and their activity events commit together. Unknown/inactive
promotions reject the whole creation with 422; duplicate email returns 409. Empty/omitted
`promotion_ids` is valid. Pending accounts can already have memberships. Invitations and activation
continue as documented in [authentication](authentication.md).

## Roles and permissions

The promotion member picker excludes accounts already assigned to the selected promotion in both
pupil and teaching categories. Administrator account listing and search accept `exclude_promotion_id`
(a positive existing promotion ID), applied in SQL before counting, pagination and fuzzy ranking.
Accounts assigned to another promotion remain eligible. Removing a membership makes the account
available again; concurrent duplicate additions remain idempotent.

Valid role sets are `user` alone or any nonempty subset of `kholleur`, `teacher`, `admin`.
Student (`user`) is exclusive; staff roles combine freely. `student` is replaced by `user`.
Omitting `roles` when creating an account defaults to `user` (Élève).

Administrators can change an existing account's roles through
`PATCH /admin/users/{id}/profile` with `expected_version` and an explicit `roles` list.
The same role rules apply: empty, null, duplicate, unknown or mixed student/staff grants
return 422. Omit `roles` to preserve existing grants. Identity, private profile fields and roles
commit together; a stale version returns 409 without a partial change. A real role change increments
`profile_version` and records `user.roles_updated` with the previous/new role codes. Reordering
unchanged roles is a no-op. The service rechecks the actor's current administrator permission
inside the lifecycle lock. An administrator cannot remove their own `admin` role (409), but can
add/remove their own `teacher` role. Administrators can change other administrators' roles;
the first permanent administrator has no special owner protection.

Existing sessions use the updated role/permission grants on their next request. Account status,
passwords and invitations are preserved by role-only changes. Promotion memberships are preserved
while the account retains a pupil, teacher or khôlleur role. Losing the last eligible role removes
all memberships, including archived promotions, atomically with the profile update and records one
`promotion.member_removed` event per promotion with `reason=role_removed`. Restoring a role does
not restore memberships. A failed or stale profile update preserves both roles and memberships. Teacher access
to students follows current role and promotion membership checks, including after a role change.
Changes reuse `user_roles`, `profile_version` and the activity journal. The fresh database baseline
includes the updated deferred role constraint; see [site administration](site-administration.md).

The profile editor exposes colored role checkboxes only to administrators and requests confirmation on save
with the account name and old/new grants. Cancel preserves the draft without sending a mutation.
Other profile edits use the existing save flow. Shared badges pair an icon and label with blue for
Élève, purple for Khôlleur, dark green for Enseignant and red for Administrateur; combined roles display each badge,
including on mobile. New-account forms default/reset to Élève.
`user` cannot coexist with any other role. Creation validates the set; a deferred PostgreSQL
constraint trigger also rejects incompatible combinations after serializing changes per account.
Removing all role grants locally denies all role-specific permissions; no role-management API is added.

`permissions` and `role_permissions` separate capabilities from role names. Initial grants are:

| Role       | Permissions                                                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `user`     | `user.access`                                                                                                                              |
| `kholleur` | `kholleur.access`                                                                                                                          |
| `teacher`  | `teacher.access`, `teaching.read`, `profiles.read`, `orientation.manage`                                                                   |
| `admin`    | `users.read`, `users.manage`, `promotions.read`, `promotions.manage`, `events.read`, `statistics.read`, `profiles.read`, `profiles.manage` |

An admin-only account has no teacher permission. Any combination of staff roles receives the union of its explicit
grants. The application role cannot edit the role/permission catalogues; changes require reviewed
migrations. API dependencies and service transactions verify capabilities from current database grants.

Subject assignments, course-impact confirmations and account-archive revocation are documented in
[site administration](site-administration.md). These extend profile updates and account archival.

## Promotions and memberships

Promotions contain `id`, `year` (1–9999), `identifier` (trimmed, 1–64 characters), `color` (`#RRGGBB`),
`is_active`, `created_at`, `updated_at`. The exact `(year, identifier)` pair is unique, including archives.
Colors are returned uppercase. Permanent pupils, teachers and khôlleurs can belong to multiple
promotions regardless of activation status. Administrator alone does not confer eligibility;
administrator combined with teacher or khôlleur is eligible. The bootstrap account cannot be assigned.
Creation with memberships, individual assignment and batch assignment all enforce this rule
server-side. An ineligible account causes HTTP 422 and rejects the entire operation, without partial
accounts, assignments or audit events. Actor authorization still uses the existing management
permissions; eligibility is a business rule, not an additional administrator permission.
Historical incompatible memberships are not bulk-deleted; they remain available for manual removal.

| Method and path, under `/api/v1`                     | Permission          | Behavior                                                             |
| ---------------------------------------------------- | ------------------- | -------------------------------------------------------------------- |
| `POST /admin/promotions`                             | `promotions.manage` | Create active promotion; 201                                         |
| `GET /admin/promotions`                              | `promotions.read`   | List all states; optional `year`, `is_active`, `q` (identifier/year) |
| `GET /admin/promotions/{id}`                         | `promotions.read`   | Metadata, `member_count` and `student_count`                         |
| `PATCH /admin/promotions/{id}`                       | `promotions.manage` | Partial metadata or archive/reactivation                             |
| `GET /admin/promotions/{id}/archive-impact`          | `promotions.manage` | Preview pupil login blocks and restoration counts                    |
| `GET /admin/team`                                    | `users.manage`      | Active teaching staff grouped by active subject                      |
| `GET /admin/promotions/{id}/users`                   | `users.read`        | Paginated accounts; optional `role`, `status`                        |
| `GET /admin/users`                                   | `users.read`        | Paginated accounts; optional `role`, `status`, `promotion_id`        |
| `GET /admin/users/{id}`                              | `users.read`        | Account, activity/security dates and latest invitation state         |
| `PATCH /admin/users/{id}/archive`                    | `users.manage`      | `{"archived": true}` or `false`; revoke credentials                  |
| `POST /admin/promotions/{id}/users`                  | `promotions.manage` | Atomic addition of 1–100 `user_ids`                                  |
| `GET /admin/summary`                                 | `statistics.read`   | Global account and promotion counts                                  |
| `GET /admin/users/{id}/promotions`                   | `promotions.read`   | Memberships including archived promotions                            |
| `PUT /admin/users/{id}/promotions/{promotion_id}`    | `promotions.manage` | Idempotent addition; 204                                             |
| `DELETE /admin/users/{id}/promotions/{promotion_id}` | `promotions.manage` | Idempotent removal; 204                                              |

Lists return `items`, `total`, `offset`, `limit` (default 50, maximum 100). Accounts sort by ID;
promotions by descending year, then identifier and ID. `member_count` includes all linked permanent
accounts, including teachers/khôlleurs with administrator grants and pending/disabled accounts.
`student_count` counts only members with the `user` role, including archived/pending students.
The `role=teaching` filter combines teacher and khôlleur grants using EXISTS, so accounts holding
both roles appear once. Listing, totals, pagination and name-search ranking use the same union.

Archive with `PATCH {"is_active": false}`, reactivate with `true`. Explicit nulls are invalid.
Archiving preserves memberships and, by default, does not disable accounts. The administrator may
send `archive_students: true` with `is_active: false` and `acknowledge_student_impact: true` to
block every current permanent pupil (exclusive `user` role). The checkbox starts unchecked every time;
a warning precedes confirmation, including when pupils also belong to other promotions. Teachers,
kholleurs and administrators are unaffected. The server rejects missing acknowledgement (409) and an
archive-students command without an active-to-archived transition (422).

Each cause is recorded in `promotion_account_blocks`, independently of `users.manually_archived`.
Reactivation requires acknowledgement when recorded blocks exist, removes only this promotion's
blocks and restores only accounts free of all other blocks. Manual archives made before **or after**
a promotion archive remain effective. A membership removal or later role change does not discard the
recorded cause; it lasts until this promotion is reactivated. Repeated state changes are no-ops.
A manually requested account reactivation returns 409 while any promotion block remains.
The preview and confirmation explain how many accounts will recover and how many remain disabled.

Disabling revokes sessions and invitations immediately. Login returns the same invalid-credentials
response as an unknown account, without identifying archived accounts. Restoration uses `active` when
a password exists, otherwise `pending_activation`; old credentials are never revived. Pending users
need a newly issued invitation. All state, causes and audit facts share the lifecycle lock and one
transaction. Promotion journal entries count blocks and actual status changes; automatic account
entries identify the promotion without copying pupil names.

New associations to an archive return 409; existing memberships can be read or removed. Repeated
additions/removals do not duplicate facts.
No promotion DELETE route exists, and PostgreSQL denies runtime DELETE on `promotions`.

Account archiving sets status `disabled` and `archived_at`, revokes all sessions and invitations,
and preserves memberships and history. An administrator cannot archive their own account (409).
Reactivation clears `archived_at` and restores `active` when a password exists, otherwise
`pending_activation`. Revoked credentials are never restored. No account deletion route exists.
Summary counts exclude the bootstrap: total = active + pending activation + archived. A pending
account is counted even if its invitation has not yet been issued; the UI labels this category
as accounts awaiting activation.

## Teaching team

The administrator-only `/dashboard?tab=team` reads `GET /admin/team`. Every active subject has a
colored block, including subjects without staff. Only active, assigned teachers and kholleurs appear.
The page shows teachers first, then kholleurs, sorted within each role by accent-insensitive family
name, given name and ID. Each name links to the full profile inside the badge for that teaching role,
even when the account is also an administrator. A person with both staff roles appears twice per
subject: once as a teacher and once as a kholleur. There is no subject search bar.
No emails or private profile fields are returned. The API retains one member per subject with all
explicit roles; the page expands teaching roles for display. `member_count` counts unique displayed
accounts across all subjects. `teacher_count` and `kholleur_count` count occurrences per subject,
independently: a dual-role account contributes to both totals for each assigned active subject.
Assignments are maintained in the administrator profile editor for either staff role.
They do not add course collaborations or confer automatic course access.

## Teacher directory

`teaching.read` permits only read operations. The teacher must share a promotion membership with
the student, checked in SQL on every request. This includes archived student accounts and assigned
archived promotions. Students outside this scope return 404. Teachers cannot access global statistics,
the journal, account management, invitations or membership changes. Admin alone does not grant this
capability; teacher/admin uses the global administrator directory in the shared UI.

- `GET /teaching/promotions`: assigned promotions; `is_active`, identifier `q`, pagination.
- `GET /teaching/users`: students only; optional authorized `promotion_id`, pagination.
- `GET /teaching/users/search`: same scope and name/username matching as the administrator search.
- `GET /teaching/users/{id}`: restricted identity card and shared promotions only.

Teacher cards exclude email, permissions, invitation details and security/login history. Pedagogical
statistics are reserved for future features; the first draft does not invent activity metrics.
`GET /auth/me/promotions` returns only the authenticated account's own promotion badges.

## Complete school profiles

The full detail page `/dashboard/user?id=123` loads private information separately from account
lists and the compact account drawer. Integer IDs identify the target; they never grant access.
The username is immutable, even after first/family-name edits. Existing setup and account creation
forms remain minimal; optional school details can be completed after creation.

All optional school fields reside in `users` as nullable encrypted columns: `birth_date_encrypted`,
`city_encrypted`, `postal_code_encrypted`, `commune_code_encrypted`, `previous_school_encrypted`,
`baccalaureate_encrypted`, `orientation_project_encrypted`, `phone_encrypted`, and
`reference_adult_encrypted`. Each contains an authenticated JSON value encrypted by the same
row/field-bound AES-256-GCM keyring as identities. Structured diploma/contact values remain encrypted
as a whole, without plaintext JSONB copies. HMAC is used for existing exact username/email indexes,
not as encryption. `rotate-identities` includes every new encrypted field.

- Birth date: optional date, cannot be in the future; age is derived on read and never persisted.
- Location: optional canonical commune name, INSEE code and five-digit postcode, modified together.
- Previous school: optional text, maximum 200 characters.
- Baccalaureate: optional label (100 characters), obtained year (1900 through current year),
  overall mark and up to 20 uniquely named subjects/options (100 characters each), each with an
  optional mark. All marks accept decimals from 0 through 20, including zero.
- Orientation project: optional text, maximum 200 characters.
- Phone: French national format is normalized to `+33`; international `+` or `00` formats are
  accepted, with 7–15 digits. This validates formatting, not ownership or actual service availability.
- Reference adult: optional object with required first name, family name and phone when present.
  Names follow the existing French-name validation; contact phone uses the same normalization.

| Method and path, under `/api/v1`     | Access                                                                                                               |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `GET /auth/me/profile`               | Own complete profile; no self-editing permission is granted                                                          |
| `GET /admin/users/{id}/profile`      | Administrator with `profiles.read`                                                                                   |
| `PATCH /admin/users/{id}/profile`    | Administrator with `profiles.manage`; names/email, roles and school fields; role changes also require `users.manage` |
| `GET /teaching/users/{id}/profile`   | Teacher with `profiles.read`, student in a shared promotion                                                          |
| `PATCH /teaching/users/{id}/profile` | Teacher with `orientation.manage`; orientation project only                                                          |
| `GET /admin/communes?q=Paris`        | Administrator with `profiles.manage`; public reference suggestions                                                   |

Teachers may read the new full profile (including contact details) only for their shared students,
including archived accounts. Their existing compact directory DTO still excludes private details and
security/login history. Unrelated students return 404; extra fields in a teacher patch return 422.
An administrator may edit any permanent account, including archived accounts; bootstrap is excluded.

PATCH accepts `expected_version` from the response's `profile_version`. The service rechecks current
permissions/membership inside the lifecycle transaction, locks the target and returns 409 for a stale
version. Changes commit atomically, increment the version and append `user.profile_updated` containing
only changed field names. An unchanged patch emits no event. Explicit null clears optional data;
names/email cannot be null. Duplicate email returns 409 and rolls back every other change. Email
changes update the HMAC index, clear verification and revoke outstanding invitations; passwords,
sessions, username and memberships are preserved. Account-level timestamps are updated on real edits.

Autocomplete uses the free, open [API Découpage administratif](https://geo.api.gouv.fr/decoupage-administratif/communes)
over HTTPS without an API key, paid provider or new dependency. Only the commune/postcode query is
sent, never an account ID/name. The backend normalizes saved names against the selected INSEE code
and checks that the postcode belongs to it; browser suggestions alone are not a validation control.
Requests have a three-second timeout, bounded responses, four concurrent fetches and a public-data
cache of at most 256 queries with a six-hour TTL. The browser debounces 250 ms and cancels obsolete
requests. Upstream failures return a sanitized 503 and preserve the existing location. Cancel an
unfinished search to save other edits; unchanged location fields require no upstream validation.
The API's access-log filter strips commune query text; host proxies must also redact BFF queries.

Existing 0001 is amended with explicit owner authorization for a fresh disposable installation;
no new migration is introduced. Rebuild/recreate the authorized test database before using this
rewritten schema against a previously stamped database. Development data is never reset by code.

## Promotion group partitions

The promotion detail in `/dashboard` provides independent half (`halves`), third (`thirds`)
and khôlle (`kholles`) partitions. Half/third labels are Groupe A, B and C; khôlle labels are
Groupe 01, 02, etc. Each created partition covers all permanent pupils currently attached to
the promotion, including pending and archived accounts, and excludes teaching staff.

Administrators generate randomized drafts and explicitly save them. Half/third generation balances
sizes with at most one pupil difference. Khôlle generation defaults to a target of three pupils,
selectable from two through five. The target determines the number of groups using ceiling division;
pupils fill each group to the target, with at most one smaller group containing the remainder
(seven pupils with target three gives 3/3/1). During manual editing, temporary imbalance is allowed.
Saving halves/thirds requires at most one pupil difference. Saving khôlles requires the exact target
in every group, except for a single group containing the remainder when division is not exact.
For 45 pupils and target three, all 15 groups must contain three pupils; 5/1 and 4/2 splits are
rejected. For 46 pupils, 15 groups of three and one group of one are required. The remainder group
can have any number in the sequence. Every pupil must occur exactly once per partition.
Empty khôlle bubbles must be filled or removed. Half/third bubbles can be empty for tiny rosters.

The board supports movable bubbles, drag/drop student transfer, click/keyboard transfer and a list
view on small screens. Saved positions are shared; consultation movements are temporary.
Cancel discards the draft. Deleting a partition requires confirmation and preserves promotion
memberships and all other partitions. Regeneration also requires confirmation and creates a draft
without changing the published partition until save.

Promotion member rows, the pupil popup and `/dashboard/user?id=…` display compact saved group
tags: letters for halves/thirds and padded numbers for khôlles. Blue, violet and green distinguish
the three kinds; accessible labels and tooltips name the kind. Missing assignments render no tag.
The complete profile groups promotion badges and their group tags in a dedicated section.
Saving/deleting a partition refreshes the promotion member list.

Administrator/teacher account lists, searches, pupil popup responses and complete profiles include
`group_assignments`: minimal `{promotion_id, kind, number}` references. A promotion-filtered list
or search includes only that promotion's tags. Other administrator directory reads include all
current pupil assignments; teacher reads include only promotions currently shared with the caller,
even when the pupil belongs to other promotions. Full-profile references follow that profile's
already-authorized promotion list. These fields are not added to session/authentication responses.
Assignments are batch-loaded for returned directory rows; no per-pupil HTTP/SQL request is needed.
Deleted partitions/memberships disappear on subsequent reads, and old assignments of accounts
that no longer have the pupil role are excluded. Existing read-only/authorization rules apply;
no schema migration or new permission is introduced for these tags.

`/api/v1/promotion-groups` exposes:

| Method and suffix | Behavior |
| --- | --- |
| `GET /promotions` | Paginated promotion catalogue inside staff scope |
| `GET /promotions/{id}` | Scoped promotion display metadata |
| `GET /{id}` | Current pupil names/IDs and all saved partitions |
| `POST /{id}/{kind}/preview` | Administrator-only random draft, without persistence |
| `PUT /{id}/{kind}` | Administrator-only atomic validated replacement |
| `DELETE /{id}/{kind}` | Administrator-only removal of one partition |

Administrators use `promotions.read`/`promotions.manage`; teachers with `teaching.read` and khôlleurs
with `kholleur.access` can only consult promotions to which they are currently attached. Unrelated
promotions return 404. Student accounts have no access. Khôlleur dashboard access does not grant
student profiles, teacher statistics or other teaching APIs. Existing authentication, no-store,
JSON and CSRF protections apply. Archived promotions are read-only, including for administrators.

Preview/save bodies contain `expected_revision` (null for an absent partition), `roster_ids` and
`target_size` (default 3). Save also includes `groups` with sequential `number`, bounded integer
`x`/`y`, and `student_ids`. Delete contains only `expected_revision`. Unknown fields are rejected.
A stale partition or roster returns 409 without partial changes. Writes share the existing lifecycle
lock with membership and role changes. New pupils remain unassigned in existing partitions until
administrator action; removing a promotion membership cascades its group assignments. A former
pupil's assignments are excluded when reading after a role change; saving replaces those stale rows.
No automatic reshuffle occurs. The current roster and revision are checked again on save.

Migration `0006_promotion_groups` adds `promotion_partitions`, `promotion_groups` and
`promotion_group_members`; it preserves existing accounts, memberships and applied migrations.
Composite foreign keys enforce promotion membership and group identity; a composite primary key
prevents multiple assignments within one partition. Atomic activity events `promotion.groups_saved`
and `promotion.groups_deleted` record partition kind and aggregate counts, never pupil identities.
Apply with `alembic upgrade head` before using the feature. Existing Compose migration startup
also applies this revision. No new dependency or external service is required.

## Interactive search

`GET /api/v1/admin/users/search?q=valentin%20burgo&limit=20` requires `users.read`.
Queries contain 2–100 characters; limit is 1–20. Optional `role`, `status`, `promotion_id` filters
restrict candidates before decryption. Results contain `id`, `username`, `first_name`, `last_name`,
`status`, without email. The bootstrap is excluded.

Search ignores case, accents, French ligatures and separators; accepts either name order, partial
names and approximate spelling. Exact and prefix matches precede approximate matches. Two/three-letter
queries use stricter matching. Matching uses RapidFuzz (MIT), with no external service or persistent
plaintext search index. Name preparation and ranking run off the event loop. A per-worker memory cache
holds at most 20,000 decrypted name preparations with a 60-second TTL checked on each search; expired
entries are removed on subsequent searches and all references are cleared at shutdown. It contains no
emails, permissions, memberships or search results. Each request selects current candidates in SQL and
compares their encrypted name fields before cache reuse, so identity changes invalidate immediately and
removed memberships/revoked permissions cannot be restored by cached data. Usernames of current
candidates are decrypted for literal substring/prefix matching; they are not added to the name cache.
Ordinary dashboard lists still decrypt only a page.

The algorithm scans filtered candidates, so its cost grows with the account count. Performance must
be measured with realistic volumes and concurrency; it is not an indexed SQL fuzzy search. The
frontend debounces 220 ms, waits for two characters and cancels obsolete requests.
The backend strips administrator/teacher search query strings from Uvicorn access entries. Reverse proxies must
also exclude it from their own access logs if they normally record URLs. No search event is written
to the activity journal.
The public BFF route `/dashboard/data` also carries search text in its query string; exclude that
query from host proxy/access analytics logs.

The PostgreSQL performance regression uses synthetic encrypted accounts at 2,000 and 10,000 rows,
a warm cache and concurrent authenticated requests, with a broad two-second ceiling to avoid flaky
CI. This is not a user-facing latency guarantee. Earlier name-only measurements predate username
substring matching and should not be treated as measurements of this implementation. Cold requests
must also prepare names; realistic production latency depends on hardware, volume and concurrency.

## Activity journal

`activity_events` replaces `login_events`. Fields: integer `id`, UTC-aware `occurred_at`, `event_type`,
`schema_version`, optional `actor_user_id`, `subject_user_id`, `resource_type`, `resource_id`, and bounded
JSONB `data`. Historical `actor_role` and `subject_role` preserve the highest explicit role
(`admin` > `teacher` > `kholleur` > `user`) at the action. Null means a system or unknown role, never an inferred
student role. Account references are foreign keys with `RESTRICT`, preserving event referents.
`promotion_snapshot` contains the historical identifier, year and validated hexadecimal color;
non-promotion events use SQL NULL. Account names remain in their existing encrypted user records.
The journal displays current names with historical roles; bootstrap references have no profile link.
Resource type/ID pairs are generic references validated by the emitting business service, not universal
foreign keys. An event does not authorize access to its resource.

Current event codes:

- `auth.login_succeeded`: actor and subject are the authenticated account.
- `user.created`: actor is the creator, subject is the new account.
- `user.archived`, `user.reactivated`, `invitation.issued`, `auth.password_reset`.
- `user.profile_updated`, `user.roles_updated`.
- `promotion.created`, `promotion.updated`, `promotion.archived`, `promotion.reactivated`.
- `promotion.member_added`, `promotion.member_removed`: actor, affected account and promotion.

Events and their successful business actions share one transaction. No-op changes emit no extra fact;
rollback leaves neither the mutation nor its success event. JSON is an object capped at 4 KiB and is
validated against explicit per-event Pydantic schemas, not arbitrary browser input. Promotion updates
store `changed_fields` and validated previous/current catalogue values. Account creation records
initial grants. Role changes preserve the full before/after combinations and snapshot the target's
role before replacement. Profile changes record field names only, never private old/new values.
Personal identities, passwords, tokens and raw request bodies are excluded. Participant roles are
batch-loaded and reused only inside the business transaction. Changing roles invalidates that
participant's cached snapshot for subsequent events. Bulk membership changes preload all participants.

`GET /admin/events` requires `events.read`. It accepts `limit`, `cursor`, `event_type`, `actor_user_id`,
`subject_user_id`, `resource_type`, `resource_id`, `since`, `until`, and `order=desc|asc` (default `desc`).
Dates require explicit timezones; the period is inclusive. Occurrence time and ID break ties. SQL
selects at most `limit + 1` journal rows and returns at most `limit`, with an opaque `next_cursor`.
Cursors bind their position to the order and filters; malformed or mismatched cursors return 422.
Timestamp/ID and type/timestamp/ID indexes support both directions without total counts or deep
OFFSET queries. Participant names for the returned page use one grouped read. Roles and promotion
display metadata require no related lookups.

`GET /admin/events/types` requires current `events.read` permission and exposes the live `EVENTS`
catalogue with `code`, French `label`, icon key and safe message template. It never scans journal rows:
new types appear before their first occurrence. Only `{actor}`, `{subject}`, `{promotion}`, `{roles}`
placeholders are accepted. The frontend renders escaped text and Svelte components, never HTML or
executable templates. Unknown icons fall back to the clock icon.

The frontend shows 15 events per page, a type filter (default all) and newest/oldest ordering.
Changing the filter/order resets to page 1. Previous/next buttons display the visited page number;
next is disabled when `next_cursor` is null. Changed selections cancel requests and ignore stale
responses. Member tags link to existing profiles; promotion tags link to
`/dashboard?tab=promotions&promotion=<id>&edit=1`. That destination rechecks administrator access,
loads the current promotion and opens its existing configuration. Full role combinations appear in
transitions, including when the highest role is unchanged. Archived resources retain their existing
access policies. There are no event mutation endpoints. Runtime grants allow SELECT/INSERT only.
This is an append-only application journal, not a tamper-proof record against database administrators.

To add, for example, `test.completed`, declare its metadata schema, label, icon and message in
`app/services/activity.py`, then `await record_event(...)` from the service's transaction after
validating the test reference. The filter and base message use that declaration automatically;
event-specific metadata details can extend the shared renderer. No table change is needed. Increment
`schema_version` and adapt readers when changing an existing payload's meaning. The frontend renders
localized sentences from codes/references; free-form rendered messages are not stored.

Successful logins still update `login_count` and `last_login_at` atomically with their event/session.
Count `auth.login_succeeded` events by `subject_user_id` for period reports. There is no automatic
retention purge; define retention before production and use a privileged maintenance procedure.

## Migrations and verification

With explicit owner authorization after deletion of the local volumes, the fresh baseline has
five initial feature revisions, followed by an additive group migration:

1. `0001_authentication`: accounts, roles/permissions, sessions, invitations, setup, login
   protection and the append-only activity journal.
2. `0002_configuration`: public site settings, shared holiday color, timelines and events.
3. `0003_promotions`: promotion catalogue and account memberships.
4. `0004_subjects`: subject catalogue and account subject assignments.
5. `0005_lessons`: course pages, content, responsibility, collaborations and promotion access.
6. `0006_promotion_groups`: independent half/third/khôlle partitions and their pupil assignments.

Use `alembic upgrade head` on a fresh database. This rewritten history does not upgrade databases
stamped with the former revisions. No persistent volume is reset by the application or tests.

Run `python -m pytest -q`, `ruff check .`, and the full disposable PostgreSQL suite using
`python run_tests.py`, from `backend/` with the configured interpreter. Integration tests verify
atomic mutations, privileges, role incompatibility, membership concurrency, archive preservation,
encryption, event pagination, search and existing authentication races. The test launcher reuses
existing Compose files and synthetic secrets without reading/modifying the local `.env`.

Subject-assignment, subject-catalogue, site-setting and calendar events now include bounded version-2
metadata. Assignment deltas include historical public subject tags and automatic removal causes;
calendar operations retain entry type, name and dates, including after deletion. Site changes expose
field names rather than copies of homepage text. Version-1 entries remain readable without invented
details. See [site administration](site-administration.md#detailed-journal-entries).
