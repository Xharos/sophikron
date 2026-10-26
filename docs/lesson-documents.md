# Private lesson documents: storage and operations

Files live in the existing Compose project's `documents_data` named volume, mounted at
`/var/lib/sophikron/documents`. PostgreSQL stores metadata and SHA-256, not a second copy of the
binary. `LessonElement.title` is the independent, editable display name; `LessonFile.original_name`
is used for downloads. `table_columns` is a generic ordered JSON list of user-defined labels,
with row/column coordinates on populated cells. No pedagogical column names are fixed in SQL.

## Setup and dependencies

Use the existing `compose.yaml` and local overlay. Trusted course editors upload documents without
antivirus scanning. Publication requires successful structural validation and current editing rights;
there is no scanner service, signature download, external scanning API or scanner availability check.
This is an explicit trust decision: format validation does not establish that a file is harmless.
A compromised teacher account can distribute malicious content within the permitted file formats.

Python dependencies added for structural validation are Pillow, pypdf and defusedxml. They provide
image decoding, PDF structure parsing and safe XML parsing for Office containers, respectively.
They are permissively licensed dependencies compatible with the project's GPL distribution;
retain their distributed license notices. ZIP inspection and hashing use the standard library.
Raw binary streaming avoids a multipart parser dependency. Keep all parsers updated; validation
limits malformed structures without certifying harmlessness.

The backend image prepares the document mount for UID 10001. Do not mount it under a public
static directory or grant other services access unnecessarily. Docker configuration does not
provide at-rest encryption; use host and backup encryption according to deployment requirements.

## Limits and configuration

`DOCUMENT_*` settings do not read `.env` directly in Python. Compose passes the allowlisted values
from the existing environment template. Defaults are:

| Setting | Default |
| --- | --- |
| `DOCUMENT_COURSE_QUOTA_BYTES` | 1 GiB |
| `DOCUMENT_USER_QUOTA_BYTES` | 5 GiB |
| `DOCUMENT_TOTAL_QUOTA_BYTES` | 20 GiB |
| `DOCUMENT_RESERVE_BYTES` | 256 MiB of free disk |
| `DOCUMENT_ROOT` | `/var/lib/sophikron/documents` in Docker |
| `DOCUMENT_UPLOAD_TIMEOUT_SECONDS` | 180 seconds |
| `DOCUMENT_MAX_CONCURRENT_DOWNLOADS` | 16 active downloads globally |

Changing advanced settings requires passing them explicitly to the backend environment. Quota
reservations count against per-course, per-uploader and total capacity. There are at most four
reservations per uploader and sixteen globally, expiring after ten minutes. Replacements reserve
the new file's capacity before releasing the previous file. Archived/deactivated uploaders do not
delete course files; ownership and current course permissions remain independent.

Set `DOCUMENT_MAX_CONCURRENT_DOWNLOADS=16` in the existing root `.env`; Compose passes it to the
backend. Values from 1 to 256 are accepted. Recreate the backend to apply a changed value.
There is no per-account download limit. When all slots are occupied, additional authenticated
requests wait in FIFO order and start automatically when a slot is released. Waiting does not
open the document or retain a SQL transaction. The service rechecks session, access and visibility
after waiting, before opening the file or calculating its SHA-256.

A slot covers preparation and the entire streamed response, including slow consumers. Errors,
disconnects and cancellations release it; a disconnected waiter is removed from the queue.
The queue is in memory and lasts only as long as the HTTP request and backend process. This cap
is global for the single backend process in the supplied Compose configuration. Running multiple
workers or backend replicas requires a shared limiter before preserving the same global cap.

The BFF forwards browser cancellation without its former three-minute download deadline. The
provided Nginx download location disables response buffering and allows up to one hour of upstream
inactivity; client and HTTP transport/proxy deadlines can still interrupt an exceptionally long wait.
This bounds concurrent streams, not bandwidth in bytes per second or the number of waiting requests.

The maximum raw body is 50 MiB. Nginx grants this only at `/lessons/upload`, with request buffering
disabled. Node's body maximum is raised to match, while the frontend hook retains the 16 KiB cap
for other writes. The API retains its small JSON-body limit for ordinary endpoints. Requests to
the exact binary route stream to a private temporary file rather than being buffered by that middleware.
File-specific limits remain 10/25/50/1 MiB as documented in `lessons.md`; larger declarations and
streams exceeding their declared byte count are rejected.

## Publication, integrity and deletion

An authorized editor reserves metadata/quota, then sends the raw file. Receipt counts bytes and
computes SHA-256. A short-lived parser subprocess validates the structure with a 30-second timeout;
Linux additionally limits address space to 512 MiB and CPU time to 20 seconds.
No uploaded code, Office program or archive is executed or extracted.
Images are bounded by dimensions and pixel count; archives by entry count, uncompressed size,
compression ratio, nesting and allowed paths. Office files with external relationships are refused.

The file moves atomically from `temporary/<opaque-key>` to `objects/<opaque-key>` on the same
volume before its metadata is committed. The final short transaction revalidates parent, rights
and course version. A conflict, revocation or parent deletion prevents publication. A single-use
reservation rejects duplicate/concurrent body submissions. If the final response is lost, reload
the course before attempting another deposit; this version does not provide resumable uploads
or replay the result of a successful upload request.

The editor accepts a file by click/keyboard or drag and drop, validates the existing size/type
limits and suggests a display title without the actual extension (preserving internal dots).
Only document/video resources have dates; staff-only section descendants have no date options.
Unavailable student documents retain metadata but no interactive download control. A direct API
request is still denied outside the current resource period.

Original filenames never become disk paths. Downloads require a live authorized session and are
served as attachments with `nosniff`, private `no-store`, no indexing and a safe Unicode filename.
The API checks size and SHA-256 against the opened file before sending bytes. A mismatch returns
503 rather than delivering corrupted content. This detects corruption relative to the database
reference; an attacker able to replace both bytes and metadata is outside that guarantee.

Deleting/replacing file metadata fires the PostgreSQL `lesson_file_cleanup` trigger. It records a
key in `lesson_file_deletions` in the same transaction, including for SQL cascades and bulk deletes.
The queue has no course FK, so deleting a whole course cannot erase its cleanup intent.
The file becomes inaccessible through the API immediately after commit. Application lifespan
maintenance attempts up to 100 queued deletions every thirty seconds, retaining failed jobs and
logging failures. Absent files count as success. Shutdown cancels the worker; pending jobs survive
and resume at startup. `DOCUMENT_MAINTENANCE_ENABLED=false` is used by isolated tests, not normal operation.

Maintenance also removes expired quota reservations and reconciles generated objects/temporary
files older than a day against live file metadata. It never recursively deletes a volume or
follows symlinks. The grace period exceeds the maximum upload/validation lifetime. An ambiguous
commit result must be checked against file metadata before failed-upload cleanup removes bytes.
Dates only govern visibility and never trigger physical deletion.

Monitor disk capacity and inode use, pending deletion count/age, repeated deletion warnings, quota
rejections and structural validation refusals. A backlog or disk failure can delay physical
deletion; an already downloaded copy cannot be remotely revoked.

## Backup, restore and schema changes

Back up both PostgreSQL and `documents_data` outside the host. For a consistent simple backup,
stop application writers/maintenance, take the database and document-volume backups, then restart
them together. Include the pending deletion queue and record a file-key/digest manifest. Define
retention, encryption, access control and off-host copies for the deployment.

Test restores to a separate installation. Restore matched database/filesystem backups, validate
file sizes/digests and permissions, then let the durable deletion queue drain before reopening
access. Reconcile stale files from older backups so deleted documents do not reappear. Active
storage deletion does not erase existing backups: their retention and any deletion register
needed across restore points must be part of the operating procedure.

Never use `docker compose down --volumes` against a valued installation: it removes documents as
well as PostgreSQL data. No persistent application data was reset by development verification.

The user explicitly authorized amending `0005_lessons`. It now creates file metadata, upload
reservations and deletion jobs together with dynamic tables/audiences. Existing databases already
at that revision require a separately reviewed transition; `alembic upgrade head` does not replay
an amended migration. Downgrading 0005 refuses when files or deletion jobs remain. Do not delete
valuable course data to bypass that guard.

## Verification

The [current security audit](security-audit.md) records verification after antivirus removal,
the cancelled-download fix, and the additional authorization/quota regression tests.

`tests/test_document_storage.py` checks actual supported file structures, hostile archives,
streaming/hash limits and actual subprocess validation/publication. `tests/test_lesson_documents_postgres.py`
checks real disk operations, PostgreSQL cascades, free table labels, independent cells, staff-only
subtrees, live dates/access, replacements, stale uploads, storage failures, integrity errors
and durable deletion retry. Parsing, database and filesystem operations remain real.

Frontend unit tests verify binary BFF routing, credentials, limits and response headers. Browser
journeys cover arbitrary table titles, private/empty cells, document display-name selection and
pre-transfer size refusal on desktop/mobile alongside existing course flows.

Historical verification before the antivirus removal (these counts do not describe the current run):

- `python -m pytest -q`: 189 passed, 117 integration cases skipped without the dedicated database.
- `python run_tests.py --tb=short` with `BFF_INTEGRATION=1` and `BFF_BROWSER_INTEGRATION=1`:
  305 tests passed on disposable PostgreSQL, plus HTTP and desktop/mobile browser journeys.
- After the final document validation/download adjustments,
  `python run_tests.py -k document --tb=short` with those flags: 18 passed, 288 deselected;
  HTTP/browser journeys passed, including table editing, display names, pre-upload limits and
  the iframe's explicit-load behavior and origin-only referrer (YouTube response intercepted locally).
- `ruff check .`, `npm test` (39 passed), `npm run check`, `npm run lint` and `npm run build`: passed.
- Both existing Compose configurations validated; backend/frontend images built successfully.
  Temporary containers, verification files and test volumes were removed.

No Git commands, persistent-database reset or deployment was performed.
