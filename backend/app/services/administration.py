"""Authorized dashboard operations with atomic membership changes and activity facts."""

import base64
import hashlib
import json
import unicodedata
from collections.abc import Sequence
from datetime import datetime

import anyio
from sqlalchemy import Row, String, cast, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError

from app.models import (
    AccountInvitation,
    ActivityEvent,
    Permission,
    Promotion,
    Role,
    RolePermission,
    User,
    UserPromotion,
    UserRole,
)
from app.repositories.administration import AdministrationRepository
from app.schemas.administration import (
    AccountArchive,
    AdminAccountResponse,
    DashboardSummary,
    EventPage,
    EventResponse,
    EventTypeResponse,
    InvitationState,
    MembershipBatch,
    PromotionCreate,
    PromotionPage,
    PromotionResponse,
    PromotionUpdate,
    SearchResult,
    UserPage,
)
from app.schemas.auth import UserResponse
from app.services.activity import EVENTS, capture_roles, record_event
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.search import rank_prepared_names


class AdministrationService:
    """Reuse authentication resources while owning each complete business transaction."""

    def __init__(self, auth: AuthService) -> None:
        """Bind the request-scoped authentication service and shared database session."""
        self.auth = auth
        self.db = auth.db
        self.repo = AdministrationRepository(self.db)

    async def _promotion(self, promotion_id: int, *, lock: bool = False) -> Promotion:
        """Require an existing promotion, including archived promotions."""
        promotion = await self.repo.promotion(promotion_id, lock=lock)
        if promotion is None:
            raise AuthError(404, "Promotion introuvable.")
        return promotion

    async def _user(self, user_id: int, *, lock: bool = False) -> User:
        """Require a permanent account, regardless of its activation or role status."""
        user = await self.auth.repo.user(user_id, lock=lock)
        if user is None or user.is_bootstrap:
            raise AuthError(404, "Compte introuvable.")
        return user

    async def _promotion_profiles(self, promotions: list[Promotion]) -> list[PromotionResponse]:
        """Build response models with one grouped membership count query."""
        counts = await self.repo.member_counts([item.id for item in promotions])
        students = await self.repo.student_counts([item.id for item in promotions])
        return [
            PromotionResponse(
                id=item.id,
                year=item.year,
                identifier=item.identifier,
                color=item.color,
                is_active=item.is_active,
                created_at=item.created_at,
                updated_at=item.updated_at,
                member_count=counts.get(item.id, 0),
                student_count=students.get(item.id, 0),
            )
            for item in promotions
        ]

    async def _profiles(self, users: list[User]) -> list[UserResponse]:
        """Batch-load roles and permissions before decrypting only this response page."""
        ids = [user.id for user in users]
        roles: dict[int, list[str]] = {}
        for user_id, code in await self.db.execute(
            select(UserRole.user_id, Role.code).join(Role).where(UserRole.user_id.in_(ids))
        ):
            roles.setdefault(user_id, []).append(code)
        permissions: dict[int, set[str]] = {}
        for user_id, code in await self.db.execute(
            select(UserRole.user_id, Permission.code)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission)
            .where(UserRole.user_id.in_(ids))
        ):
            permissions.setdefault(user_id, set()).add(code)
        return [
            await self.auth._profile(
                user,
                roles=tuple(sorted(roles.get(user.id, []))),
                permissions=tuple(sorted(permissions.get(user.id, set()))),
            )
            for user in users
        ]

    async def create_promotion(
        self, actor: UserContext, data: PromotionCreate
    ) -> PromotionResponse:
        """Create a catalogue entry and record its creation in the same transaction."""
        try:
            async with self.db.begin():
                await self.auth._actor(actor, permission="promotions.manage")
                promotion = Promotion(**data.model_dump(), is_active=True)
                self.db.add(promotion)
                await self.db.flush()
                await record_event(
                    self.db,
                    "promotion.created",
                    actor.id,
                    resource_type="promotion",
                    resource_id=promotion.id,
                )
                return (await self._promotion_profiles([promotion]))[0]
        except IntegrityError:
            raise AuthError(409, "Cette promotion existe déjà.") from None

    async def update_promotion(
        self, actor: UserContext, promotion_id: int, data: PromotionUpdate
    ) -> PromotionResponse:
        """Apply a partial update with archive/reactivation facts only on actual changes."""
        try:
            async with self.db.begin():
                await self.auth._actor(actor, permission="promotions.manage")
                promotion = await self._promotion(promotion_id, lock=True)
                previous = {
                    field: getattr(promotion, field) for field in ("identifier", "year", "color")
                }
                changes = {
                    key: value
                    for key, value in data.model_dump(exclude_unset=True).items()
                    if getattr(promotion, key) != value
                }
                for key, value in changes.items():
                    setattr(promotion, key, value)
                if changes:
                    promotion.updated_at = self.auth.clock()
                    fields = sorted(set(changes) - {"is_active"})
                    if fields:
                        await record_event(
                            self.db,
                            "promotion.updated",
                            actor.id,
                            resource_type="promotion",
                            resource_id=promotion.id,
                            data={
                                "changed_fields": fields,
                                "previous": previous,
                                "current": {field: getattr(promotion, field) for field in previous},
                            },
                        )
                    if "is_active" in changes:
                        event = (
                            "promotion.reactivated" if promotion.is_active else "promotion.archived"
                        )
                        await record_event(
                            self.db,
                            event,
                            actor.id,
                            resource_type="promotion",
                            resource_id=promotion.id,
                        )
                await self.db.flush()
                return (await self._promotion_profiles([promotion]))[0]
        except IntegrityError:
            raise AuthError(409, "Cette promotion existe déjà.") from None

    async def promotions(
        self,
        actor: UserContext,
        *,
        year: int | None,
        is_active: bool | None,
        offset: int,
        limit: int,
        user_id: int | None = None,
        q: str | None = None,
    ) -> PromotionPage:
        """List promotions with optional archive, year and account filters."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="promotions.read")
            statement = select(Promotion)
            if user_id is not None:
                await self._user(user_id)
                statement = statement.join(UserPromotion).where(UserPromotion.user_id == user_id)
            if year is not None:
                statement = statement.where(Promotion.year == year)
            if is_active is not None:
                statement = statement.where(Promotion.is_active == is_active)
            if q:
                value = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(
                    or_(
                        Promotion.identifier.ilike(f"%{value}%", escape="\\"),
                        cast(Promotion.year, String).contains(q.strip()),
                    )
                )
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            items = list(
                (
                    await self.db.scalars(
                        statement.order_by(
                            Promotion.year.desc(), Promotion.identifier, Promotion.id
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return PromotionPage(
                items=await self._promotion_profiles(items), total=total, offset=offset, limit=limit
            )

    async def promotion(self, actor: UserContext, promotion_id: int) -> PromotionResponse:
        """Return one promotion and its membership count."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="promotions.read")
            return (await self._promotion_profiles([await self._promotion(promotion_id)]))[0]

    async def membership(
        self, actor: UserContext, user_id: int, promotion_id: int, *, add: bool
    ) -> None:
        """Idempotently add/remove an association, preserving archived promotion history."""
        async with self.db.begin():
            # Match account-creation lock order before locking individual accounts/promotions.
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, permission="promotions.manage")
            await self._user(user_id, lock=True)
            promotion = await self._promotion(promotion_id, lock=True)
            membership = await self.db.get(UserPromotion, (user_id, promotion_id))
            if add and membership is None:
                if not promotion.is_active:
                    raise AuthError(409, "Cette promotion est inactive.")
                self.db.add(UserPromotion(user_id=user_id, promotion_id=promotion_id))
            elif not add and membership is not None:
                await self.db.delete(membership)
            else:
                return
            await record_event(
                self.db,
                "promotion.member_added" if add else "promotion.member_removed",
                actor.id,
                subject_user_id=user_id,
                resource_type="promotion",
                resource_id=promotion_id,
            )

    async def users(
        self,
        actor: UserContext,
        *,
        role: str | None,
        status: str | None,
        promotion_id: int | None,
        offset: int,
        limit: int,
    ) -> UserPage:
        """Return a filtered stable page without loading or decrypting other accounts."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="users.read")
            if promotion_id is not None:
                await self._promotion(promotion_id)
            statement = self.repo.users_statement(
                role=role, status=status, promotion_id=promotion_id
            )
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            users = list(
                (
                    await self.db.scalars(statement.order_by(User.id).offset(offset).limit(limit))
                ).all()
            )
            return UserPage(
                items=await self._profiles(users), total=total, offset=offset, limit=limit
            )

    async def add_members(
        self, actor: UserContext, promotion_id: int, data: MembershipBatch
    ) -> None:
        """Assign all selected accounts atomically and journal only newly added memberships."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, permission="promotions.manage")
            ids = set(data.user_ids)
            users = list(
                (
                    await self.db.scalars(
                        select(User)
                        .where(User.id.in_(ids), User.is_bootstrap.is_(False))
                        .order_by(User.id)
                        .with_for_update()
                    )
                ).all()
            )
            if len(users) != len(ids):
                raise AuthError(422, "Un compte sélectionné n’existe pas.")
            promotion = await self._promotion(promotion_id, lock=True)
            if not promotion.is_active:
                raise AuthError(409, "Cette promotion est inactive.")
            existing = set(
                (
                    await self.db.scalars(
                        select(UserPromotion.user_id).where(
                            UserPromotion.promotion_id == promotion_id,
                            UserPromotion.user_id.in_(ids),
                        )
                    )
                ).all()
            )
            await capture_roles(self.db, (ids - existing) | {actor.id})
            for user_id in sorted(ids - existing):
                self.db.add(UserPromotion(user_id=user_id, promotion_id=promotion_id))
                await record_event(
                    self.db,
                    "promotion.member_added",
                    actor.id,
                    subject_user_id=user_id,
                    resource_type="promotion",
                    resource_id=promotion_id,
                    promotion=promotion,
                )

    async def user(self, actor: UserContext, user_id: int) -> AdminAccountResponse:
        """Return a permanent account's authorized identity."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="users.read")
            user = await self._user(user_id)
            profile = (await self._profiles([user]))[0]
            invitation = await self.db.scalar(
                select(AccountInvitation)
                .where(AccountInvitation.user_id == user_id)
                .order_by(AccountInvitation.id.desc())
                .limit(1)
            )
            state = "none"
            if invitation is not None:
                state = (
                    "used"
                    if invitation.used_at
                    else "revoked"
                    if invitation.revoked_at
                    else "expired"
                    if invitation.expires_at <= self.auth.clock()
                    else "pending"
                )
            return AdminAccountResponse(
                **profile.model_dump(),
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
                password_changed_at=user.password_changed_at,
                email_verified_at=user.email_verified_at,
                login_count=user.login_count,
                archived_at=user.archived_at,
                invitation=InvitationState(
                    status=state,
                    expires_at=invitation.expires_at if invitation else None,
                    purpose=invitation.purpose if invitation else None,
                ),
            )

    async def summary(self, actor: UserContext) -> DashboardSummary:
        """Aggregate counts in SQL without decrypting account identities."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="statistics.read")
            counts = dict(
                (
                    await self.db.execute(
                        select(User.status, func.count())
                        .where(User.is_bootstrap.is_(False))
                        .group_by(User.status)
                    )
                ).all()
            )
            total, active = (
                await self.db.execute(
                    select(
                        func.count(Promotion.id),
                        func.count(Promotion.id).filter(Promotion.is_active),
                    )
                )
            ).one()
            return DashboardSummary(
                total_accounts=sum(counts.values()),
                pending_accounts=counts.get("pending_activation", 0),
                active_accounts=counts.get("active", 0),
                archived_accounts=counts.get("disabled", 0),
                total_promotions=total,
                active_promotions=active,
            )

    async def archive_account(self, actor: UserContext, user_id: int, data: AccountArchive) -> None:
        """Archive/reinstate accounts atomically, preserving identity, password and memberships."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, permission="users.manage")
            user = await self._user(user_id, lock=True)
            if data.archived and user.id == actor.id:
                raise AuthError(409, "Vous ne pouvez pas archiver votre propre compte.")
            if data.archived == (user.status == "disabled"):
                return
            now = self.auth.clock()
            user.status = (
                "disabled"
                if data.archived
                else ("active" if user.password_hash is not None else "pending_activation")
            )
            user.archived_at = now if data.archived else None
            user.updated_at = now
            await self.auth.repo.revoke_sessions(user.id, now, "account_archived")
            await self.auth.repo.revoke_invitations(user.id, now)
            await record_event(
                self.db,
                "user.archived" if data.archived else "user.reactivated",
                actor.id,
                subject_user_id=user.id,
            )

    async def search(
        self,
        actor: UserContext,
        query: str,
        *,
        role: str | None,
        status: str | None,
        promotion_id: int | None,
        limit: int,
    ) -> list[SearchResult]:
        """Search authorized candidate names and usernames transiently in memory."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="users.read")
            if promotion_id is not None:
                await self._promotion(promotion_id)
            statement = self.repo.users_statement(
                role=role, status=status, promotion_id=promotion_id
            )
            rows = (
                await self.db.execute(
                    statement.with_only_columns(
                        User.id,
                        User.first_name_encrypted,
                        User.last_name_encrypted,
                        User.username_encrypted,
                        User.status,
                    )
                )
            ).all()
        return await self.match_search(rows, query, limit)

    async def match_search(self, rows: Sequence[Row], query: str, limit: int) -> list[SearchResult]:
        """Rank already authorized candidate rows; callers must apply their own scope in SQL."""
        cipher = self.auth.cipher

        def match() -> list[SearchResult]:
            """Reuse bounded name preparations without ever caching permissions or membership."""
            names = self.auth.name_search_cache.prepare(
                [(row.id, row.first_name_encrypted, row.last_name_encrypted) for row in rows],
                cipher,
            )
            matches = rank_prepared_names(query, names, limit)
            stored = {row.id: row for row in rows}
            username_query = "".join(
                char
                for char in unicodedata.normalize("NFKD", query.lower())
                if char.isascii() and char.isalnum()
            )
            usernames = {
                row.id: cipher.decrypt(row.id, "username", row.username_encrypted) for row in rows
            }
            direct = sorted(
                (
                    user_id
                    for user_id, value in usernames.items()
                    if len(username_query) >= 2 and username_query in value
                ),
                key=lambda user_id: (
                    usernames[user_id] != username_query,
                    not usernames[user_id].startswith(username_query),
                    user_id,
                ),
            )
            matches = list(dict.fromkeys(direct + matches))[:limit]
            return [
                SearchResult(
                    id=user_id,
                    first_name=names[user_id].first_name,
                    last_name=names[user_id].last_name,
                    username=usernames[user_id],
                    status=stored[user_id].status,
                )
                for user_id in matches
            ]

        return await anyio.to_thread.run_sync(match)

    async def event_types(self, actor: UserContext) -> list[EventTypeResponse]:
        """Return the authorized live catalogue, including types without recorded events.

        Parameters
        ----------
        actor
            Principal whose current journal permission must be checked.

        Returns
        -------
        list[EventTypeResponse]
            Registered labels, icons and safe message templates.
        """
        async with self.db.begin():
            await self.auth._actor(actor, permission="events.read")
            return [
                EventTypeResponse(
                    code=code,
                    label=item.label if item.label != "Événement" else code,
                    icon=item.icon,
                    message=item.message,
                )
                for code, item in EVENTS.items()
            ]

    async def events(
        self,
        actor: UserContext,
        *,
        cursor: str | None,
        limit: int,
        event_type: str | None,
        actor_user_id: int | None,
        subject_user_id: int | None,
        resource_type: str | None,
        resource_id: int | None,
        since: datetime | None,
        until: datetime | None,
        order: str = "desc",
    ) -> EventPage:
        """Return one chronological cursor page with historical roles and grouped identities."""
        if order not in {"asc", "desc"}:
            raise AuthError(422, "Ordre invalide.")
        if since is not None and until is not None and since > until:
            raise AuthError(422, "Période invalide.")
        context = json.dumps(
            [
                order,
                event_type,
                actor_user_id,
                subject_user_id,
                resource_type,
                resource_id,
                since.isoformat() if since else None,
                until.isoformat() if until else None,
            ]
        )
        fingerprint = hashlib.sha256(context.encode()).hexdigest()[:16]
        async with self.db.begin():
            await self.auth._actor(actor, permission="events.read")
            statement = select(ActivityEvent)
            for column, value in (
                (ActivityEvent.event_type, event_type),
                (ActivityEvent.actor_user_id, actor_user_id),
                (ActivityEvent.subject_user_id, subject_user_id),
                (ActivityEvent.resource_type, resource_type),
                (ActivityEvent.resource_id, resource_id),
            ):
                if value is not None:
                    statement = statement.where(column == value)
            if cursor is not None:
                try:
                    decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
                    stamp, identifier, signature = decoded.rsplit("|", 2)
                    timestamp, event_id = datetime.fromisoformat(stamp), int(identifier)
                    if timestamp.tzinfo is None or event_id <= 0 or signature != fingerprint:
                        raise ValueError
                except (ValueError, UnicodeError):
                    raise AuthError(422, "Curseur invalide.") from None
                position = tuple_(ActivityEvent.occurred_at, ActivityEvent.id)
                statement = statement.where(
                    position > (timestamp, event_id)
                    if order == "asc"
                    else position < (timestamp, event_id)
                )
            if since is not None:
                statement = statement.where(ActivityEvent.occurred_at >= since)
            if until is not None:
                statement = statement.where(ActivityEvent.occurred_at <= until)
            events = list(
                (
                    await self.db.scalars(
                        statement.order_by(
                            ActivityEvent.occurred_at.asc()
                            if order == "asc"
                            else ActivityEvent.occurred_at.desc(),
                            ActivityEvent.id.asc() if order == "asc" else ActivityEvent.id.desc(),
                        ).limit(limit + 1)
                    )
                ).all()
            )
            ids = {
                value
                for event in events[:limit]
                for value in (event.actor_user_id, event.subject_user_id)
                if value is not None
            }
            labels = {}
            bootstrap_ids = set()
            for user in await self.db.execute(
                select(
                    User.id, User.first_name_encrypted, User.last_name_encrypted, User.is_bootstrap
                ).where(User.id.in_(ids))
            ):
                if user.is_bootstrap:
                    bootstrap_ids.add(user.id)
                labels[user.id] = (
                    " ".join(
                        self.auth.cipher.decrypt(
                            user.id, field, getattr(user, field + "_encrypted")
                        )
                        for field in ("first_name", "last_name")
                    )
                    if not user.is_bootstrap
                    else "Compte d’installation"
                )
            items = []
            for event in events[:limit]:
                item = EventResponse.model_validate(event, from_attributes=True)
                item.actor_label = labels.get(event.actor_user_id)
                item.subject_label = labels.get(event.subject_user_id)
                item.actor_profile_available = (
                    event.actor_user_id in labels and event.actor_user_id not in bootstrap_ids
                )
                item.subject_profile_available = (
                    event.subject_user_id in labels and event.subject_user_id not in bootstrap_ids
                )
                item.resource_label = (
                    f"{item.promotion_snapshot.identifier} {item.promotion_snapshot.year}"
                    if item.promotion_snapshot is not None
                    else None
                )
                items.append(item)
            next_cursor = None
            if len(events) > limit:
                last = events[limit - 1]
                next_cursor = (
                    base64.urlsafe_b64encode(
                        f"{last.occurred_at.isoformat()}|{last.id}|{fingerprint}".encode()
                    )
                    .decode()
                    .rstrip("=")
                )
            return EventPage(items=items, next_cursor=next_cursor)
