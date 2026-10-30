# ADR 0007: Private document storage and trusted course editors

- **Status:** Accepted
- **Date:** 2026-10-30
- **Sources:** `0005_lessons.py`, `app/services/document_storage.py`, `file_validation.py`,
  `lesson_documents.py` and `compose.yaml`.

## Context and decision

Course files must survive container replacement without becoming publicly addressable. Keep metadata,
upload reservations and a deletion queue in PostgreSQL; keep bytes in the existing `documents_data`
volume, outside web roots. Files belong to course elements and inherit server-checked course access.
Download through authenticated API/BFF streams, with attachment disposition and no-store responses.

Validate size, allowlisted format and structure, checksum, per-course/per-uploader/global quotas and
disk reserve. Bound parser resources. Uploads are restricted to trusted editors, without antivirus;
valid format is not proof that a document is harmless. Uploaded Python/JavaScript is never executed.
Do not confuse a parser subprocess running as the backend user with a security sandbox.

SQL deletion queues make filesystem cleanup retryable across transactions and crashes. Downgrading
0005 refuses while file metadata or pending deletions remain, rather than silently orphaning bytes.
A per-process FIFO limits active downloads; permissions are rechecked after waiting and cancellation
releases the slot. Multi-worker deployments would require shared admission control.

## Consequences and alternatives

Backups must pair PostgreSQL, document bytes and the external identity keyring. PostgreSQL-only backup
is incomplete. Public static serving would bypass revocation; storing binaries directly in PostgreSQL
would enlarge database backups. A dedicated scanning sandbox would improve parser isolation but is
an architectural change requiring separate approval. There is no promise of malware-free documents.
Storage, cancellation and PostgreSQL tests cover quotas, invalid files and authorization revocation.

See [course document operations](../lessons.md#private-lesson-documents-storage-and-operations)
for the current storage and access contracts.
