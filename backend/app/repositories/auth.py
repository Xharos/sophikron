"""Parameterized authentication queries; never commit independently of a service."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountInvitation, AuthRateLimit, LoginAttempt, Role, Session, User, UserRole


@dataclass(frozen=True)
class LoginReservation:
    """Keep lease references valid even when an authentication transaction rolls back."""

    id: UUID
    ip_key: bytes
    identity_key: bytes


class AuthRepository:
    """Group account, authorization and token persistence queries."""

    def __init__(self, session: AsyncSession) -> None:
        """Use the request's session without owning its transaction."""
        self.session = session

    async def user(self, user_id: UUID, *, lock: bool = False) -> User | None:
        """Fetch an account, optionally locking it before any security-sensitive mutation."""
        statement = select(User).where(User.id == user_id).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def by_lookup(self, field: str, lookup: bytes) -> User | None:
        """Look up an exact normalized identity using only trusted column selection."""
        column = User.email_lookup if field == "email" else User.username_lookup
        return await self.session.scalar(select(User).where(column == lookup))

    async def roles(self, user_id: UUID) -> tuple[str, ...]:
        """Read current role codes rather than trusting a cookie or cached profile."""
        statement = (
            select(Role.code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code)
        )
        return tuple((await self.session.scalars(statement)).all())

    async def role_records(self, codes: list[str]) -> list[Role]:
        """Fetch role catalogue entries for a validated explicit assignment."""
        return list((await self.session.scalars(select(Role).where(Role.code.in_(codes)))).all())

    async def session_by_hash(self, digest: bytes) -> Session | None:
        """Find a session without treating its public UUID as an authentication credential."""
        return await self.session.scalar(select(Session).where(Session.token_hash == digest))

    async def invitation_by_hash(self, digest: bytes) -> AccountInvitation | None:
        """Find a candidate invitation; the service must recheck it after locking its owner."""
        return await self.session.scalar(
            select(AccountInvitation)
            .where(AccountInvitation.token_hash == digest)
            .execution_options(populate_existing=True)
        )

    async def revoke_sessions(self, user_id: UUID, now: datetime, reason: str) -> None:
        """Revoke outstanding sessions atomically while the service holds the user lock."""
        await self.session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=reason)
        )

    async def revoke_invitations(self, user_id: UUID, now: datetime) -> None:
        """Invalidate all unused links, including expired links before replacing them."""
        await self.session.execute(
            update(AccountInvitation)
            .where(
                AccountInvitation.user_id == user_id,
                AccountInvitation.used_at.is_(None),
                AccountInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def reserve_attempt(
        self,
        key: bytes,
        limit: int,
        now: datetime,
        seconds: int,
    ) -> tuple[int, datetime]:
        """Atomically consume a bounded shared budget, resetting only after expiry."""
        expired = AuthRateLimit.expires_at <= now
        statement = (
            insert(AuthRateLimit)
            .values(key=key, attempts=1, expires_at=now + timedelta(seconds=seconds))
            .on_conflict_do_update(
                index_elements=[AuthRateLimit.key],
                set_={
                    "attempts": case(
                        (expired, 1), else_=func.least(AuthRateLimit.attempts + 1, limit + 1)
                    ),
                    "expires_at": case(
                        (expired, now + timedelta(seconds=seconds)), else_=AuthRateLimit.expires_at
                    ),
                },
            )
            .returning(AuthRateLimit.attempts, AuthRateLimit.expires_at)
        )
        row = (await self.session.execute(statement)).one()
        return row.attempts, row.expires_at

    async def reserve_login(
        self,
        ip_key: bytes,
        identity_key: bytes,
        ip_limit: int,
        identity_limit: int,
        now: datetime,
        lease_seconds: int,
    ) -> tuple[LoginReservation | None, datetime | None]:
        """Reserve IP then IP/identifier capacity under row locks, before any account lookup.

        Returns
        -------
        tuple
            A pending lease, or the deadline of the exhausted failure/pending budget.
        """
        lease_expiry = now + timedelta(seconds=lease_seconds)
        for key, limit, column in (
            (ip_key, ip_limit, LoginAttempt.ip_key),
            (identity_key, identity_limit, LoginAttempt.identity_key),
        ):
            bucket = await self.session.scalar(
                insert(AuthRateLimit)
                .values(key=key, attempts=0, expires_at=lease_expiry)
                .on_conflict_do_update(
                    index_elements=[AuthRateLimit.key],
                    set_={"attempts": AuthRateLimit.attempts},
                )
                .returning(AuthRateLimit)
                .execution_options(populate_existing=True)
            )
            if bucket.expires_at <= now:
                bucket.attempts = 0
                bucket.expires_at = lease_expiry
            if bucket.attempts >= limit:
                return None, bucket.expires_at
            pending, earliest = (
                await self.session.execute(
                    select(func.count(), func.min(LoginAttempt.expires_at)).where(
                        column == key, LoginAttempt.expires_at > now
                    )
                )
            ).one()
            if bucket.attempts + pending >= limit:
                return None, min(earliest, now + timedelta(seconds=1))
        lease = LoginAttempt(
            id=uuid4(), ip_key=ip_key, identity_key=identity_key, expires_at=lease_expiry
        )
        self.session.add(lease)
        await self.session.flush()
        return LoginReservation(lease.id, ip_key, identity_key), None

    async def finish_login(
        self, lease: LoginReservation, *, failed: bool, now: datetime, seconds: int
    ) -> None:
        """Release a lease and count only an authentication failure, anchoring its fixed window."""
        buckets = []
        for key in (lease.ip_key, lease.identity_key):
            bucket = await self.session.scalar(
                select(AuthRateLimit)
                .where(AuthRateLimit.key == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            buckets.append(bucket)
        current = await self.session.get(LoginAttempt, lease.id, populate_existing=True)
        if current is None:
            return
        if failed:
            for bucket in buckets:
                if bucket.attempts == 0 or bucket.expires_at <= now:
                    bucket.attempts = 0
                    bucket.expires_at = now + timedelta(seconds=seconds)
                bucket.attempts += 1
        await self.session.delete(current)
        await self.session.flush()
        # Successful or rejected server work must not accumulate empty identifier buckets.
        for key in (lease.ip_key, lease.identity_key):
            await self.session.execute(
                delete(AuthRateLimit).where(
                    AuthRateLimit.key == key,
                    AuthRateLimit.attempts == 0,
                    ~exists().where(or_(
                        LoginAttempt.ip_key == AuthRateLimit.key,
                        LoginAttempt.identity_key == AuthRateLimit.key,
                    )),
                )
            )
