"""Owner-only calendar credentials and administrator-only revocation and rotation."""

import secrets
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from app.core.security import IdentityCipher, token_digest
from app.models import (
    Promotion,
    Role,
    TimetableCalendar,
    TimetableSubscription,
    TimetableYear,
    User,
    UserPromotion,
    UserRole,
)
from app.services.activity import record_event
from app.services.errors import AuthError
from app.services.timetable_engine import PARIS, current_school_year

if TYPE_CHECKING:
    from app.services.auth import AuthService, UserContext

Action = Literal["revoke", "regenerate"]
Category = Literal["user", "teacher", "kholleur"]


def calendar_eligibility(today: date) -> Exists:
    """Build the shared current-calendar predicate, with diffusion required only for pupils."""
    pupil = (
        select(UserRole.user_id)
        .join(Role)
        .where(UserRole.user_id == User.id, Role.code == "user")
        .correlate(User)
        .exists()
    )
    return (
        select(UserPromotion.user_id)
        .join(Promotion, Promotion.id == UserPromotion.promotion_id)
        .join(TimetableCalendar, TimetableCalendar.promotion_id == Promotion.id)
        .join(TimetableYear, TimetableYear.calendar_id == TimetableCalendar.id)
        .where(
            UserPromotion.user_id == User.id,
            Promotion.is_active.is_(True),
            TimetableCalendar.is_archived.is_(False),
            TimetableYear.school_year == current_school_year(today),
            or_(~pupil, TimetableCalendar.is_paused.is_(False)),
        )
        .correlate(User)
        .exists()
    )


async def student_promotions(db: AsyncSession, user_id: int) -> list[Promotion]:
    """Return current active pupil promotions for credential eligibility and feed names."""
    return list(
        await db.scalars(
            select(Promotion)
            .join(UserPromotion)
            .where(UserPromotion.user_id == user_id, Promotion.is_active.is_(True))
            .order_by(Promotion.year.desc(), Promotion.identifier, Promotion.id)
        )
    )


def rotate_subscription(row: TimetableSubscription, cipher: IdentityCipher, now: datetime) -> None:
    """Replace the 512-bit credential, invalidate its predecessor and restore access."""
    token = secrets.token_urlsafe(64)
    row.token_hash = token_digest(token)
    row.token_encrypted = cipher.encrypt(row.user_id, "calendar_token", token)
    row.created_at, row.revoked_at = now, None


async def ensure_subscription(
    db: AsyncSession, cipher: IdentityCipher, user: User, now: datetime
) -> TimetableSubscription:
    """Provision under the caller's user lock, preserving administrator revocation."""
    row = await db.get(TimetableSubscription, user.id)
    if row is None:
        row = TimetableSubscription(user_id=user.id)
        db.add(row)
        rotate_subscription(row, cipher, now)
    elif row.token_encrypted is None and row.revoked_at is None:
        # A legacy hash cannot recover its secret. Upgrade it once, never on every login.
        rotate_subscription(row, cipher, now)
    return row


class CalendarSubscriptionService:
    """Separate personal secrets from administrator responses and account directories."""

    def __init__(self, auth: "AuthService") -> None:
        """Reuse authentication, identity encryption and request-scoped database resources."""
        self.auth, self.db = auth, auth.db

    async def personal(self, actor: "UserContext") -> dict:
        """Return only the authenticated owner's stable link, including its revoked status."""
        async with self.db.begin():
            user = await self.auth._actor(actor)
            if user.is_bootstrap:
                raise AuthError(403, "Abonnement réservé aux comptes permanents.")
            roles = await self.auth.repo.roles(user.id)
            if "user" in roles and not await self.db.scalar(
                select(User.id).where(
                    User.id == user.id,
                    calendar_eligibility(self.auth.clock().astimezone(PARIS).date()),
                )
            ):
                return {"token": None, "revoked": False}
            row = await ensure_subscription(self.db, self.auth.cipher, user, self.auth.clock())
            return {
                "token": self.auth.cipher.decrypt(user.id, "calendar_token", row.token_encrypted)
                if row.token_encrypted is not None
                else None,
                "revoked": row.revoked_at is not None,
            }

    async def manage(
        self, actor: "UserContext", user_id: int, action: Action | None = None
    ) -> dict:
        """Read status or change one link as administrator without disclosing credentials."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, admin=True)
            user = await self.auth.repo.user(user_id, lock=True)
            if user is None or user.is_bootstrap:
                raise AuthError(404, "Compte introuvable.")
            eligible = self.auth._active(user, self.auth.clock()) and user.login_count > 0
            if action is not None and not eligible:
                raise AuthError(
                    409, "Ce compte doit être actif et s’être connecté au moins une fois."
                )
            row = await self.db.get(TimetableSubscription, user.id)
            if eligible and action is not None:
                row = await ensure_subscription(self.db, self.auth.cipher, user, self.auth.clock())
                self.apply(row, action)
                await record_event(
                    self.db, f"user.calendar_{action}", actor.id, subject_user_id=user.id
                )
            return {
                "eligible": eligible,
                "exists": row is not None,
                "revoked": row is not None and row.revoked_at is not None,
            }

    def apply(self, row: TimetableSubscription, action: Action) -> None:
        """Suspend reads or atomically replace the credential and enable its new URL."""
        if action == "revoke":
            row.revoked_at = row.revoked_at or self.auth.clock()
        else:
            rotate_subscription(row, self.auth.cipher, self.auth.clock())

    async def bulk(self, actor: "UserContext", category: Category, action: Action) -> dict:
        """Change each active previously connected category member once in one transaction."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, admin=True)
            members = select(UserRole.user_id).join(Role).where(Role.code == category)
            users = list(
                await self.db.scalars(
                    select(User)
                    .where(
                        User.id.in_(members),
                        User.status == "active",
                        User.password_hash.is_not(None),
                        User.login_count > 0,
                        ~User.is_bootstrap,
                    )
                    .order_by(User.id)
                    .with_for_update()
                )
            )
            for user in users:
                row = await ensure_subscription(self.db, self.auth.cipher, user, self.auth.clock())
                self.apply(row, action)
                await record_event(
                    self.db, f"user.calendar_{action}", actor.id, subject_user_id=user.id
                )
            return {"affected": len(users)}
