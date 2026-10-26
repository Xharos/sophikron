# ADR 0004: Accounts, promotions, capabilities and activity

- **Status:** Accepted
- **Date:** 2026-10-22

## Decision

Use independent bigint identity sequences for autonomous rows and composite keys for associations.
Keep permanent usernames immutable, generated from French names and a random 100–999 suffix. Encrypt
username, email, first name and family name with the existing row-bound AES-GCM keyring; retain exact
username/email HMAC lookups. Search partial/misspelled names transiently in the backend with RapidFuzz,
without a stored plaintext index. Measurements motivated a per-worker bounded name-preparation cache
(20,000 entries, 60-second logical TTL), validated against current selected ciphertext on every search.
Permissions and candidate membership remain database-checked and are never cached.

Separate permission grants from role names. `user` cannot coexist with any other role;
all nonempty combinations of `kholleur`, `teacher` and `admin` are allowed, with the union of their
permissions. Admin alone has no teacher permissions. Enforce incompatibilities
in services and PostgreSQL. Promotions accept all permanent account roles, including pending accounts.
Archive/reactivate promotions and accounts; preserve memberships/history. Account archiving revokes
sessions/invitations; self-archiving is forbidden. Restore pending/active from the presence of a password.
Teachers have scoped student access through shared promotions, including archived accounts.
The complete school profile permits only orientation edits for teachers; administrators may update
names/email and private school data while preserving the generated username. Full details are loaded
separately from directory/modal responses and encrypted in `users`, including the reference adult.
Profile versions prevent stale updates. The owner can read their complete profile without self-editing.
Admin alone cannot use teacher capabilities. Only administrators receive global statistics/journal access.

Record successful actions as structured versioned activity events in the business transaction.
Store actor/subject account references, generic resource references and validated bounded metadata;
derive presentation text separately. Preserve the journal through runtime SELECT/INSERT-only grants.

The owner authorized rebuilding applied development migrations because there are no retained local
volumes: 0001 accounts/authentication/permissions, 0002 promotions, 0003 events. Fold manual invitations
into 0001 and remove historical empty-baseline adoption. Future applied migrations remain immutable.

## Consequences

This supersedes ADR 0003's UUID identity, username/email-only encryption, role-based endpoint checks,
login-specific journal and historical migration compatibility decisions. Session credentials and
invitation credentials remain opaque. Invitations now distinguish first activation from active-account
password reset; automatic delivery uses SMTP when configured, otherwise a displayed manual link.
Reset consumption revokes sessions. A shared responsive frontend adopts integer IDs, generated usernames,
names and the `user` role, with modal/drawer management and a restricted teacher view.
Journal pagination orders by timestamp and ID, with opaque cursors and authorized current labels.
Fuzzy search is linear in candidate count
and remains sensitive to account volume/concurrency despite the bounded preparation cache.
See [administration](../administration.md) for API contracts and operational limits.
