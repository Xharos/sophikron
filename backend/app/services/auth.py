"""Atomic account lifecycle and server-side authentication rules."""

import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import anyio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_config import AuthSettings
from app.core.identity import username_prefix
from app.core.roles import can_join_promotion
from app.core.security import (
    TOKEN_PATTERN,
    IdentityCipher,
    PasswordSecurity,
    new_token,
    normalize_email,
    normalize_username,
    token_digest,
    validate_password,
)
from app.models import (
    AccountInvitation,
    ApplicationState,
    Promotion,
    Session,
    User,
    UserPromotion,
    UserRole,
)
from app.repositories.auth import AuthRepository
from app.schemas.administration import PromotionBadge
from app.schemas.auth import (
    AccessInvitationResponse,
    AccountResponse,
    CompleteSetupRequest,
    CreateUserRequest,
    ManualInvitationResponse,
    UserResponse,
)
from app.services.activity import record_event
from app.services.errors import (
    FORBIDDEN,
    INVALID_INVITATION,
    INVALID_REQUEST,
    LOGIN_FAILED,
    LOGIN_REQUIRED,
    AuthError,
)
from app.services.mail import InvitationMailer, MailDeliveryError
from app.services.search import NameSearchCache
from app.services.statistics_recording import record_login_failure

# Serialize rare multi-account lifecycle operations in a consistent lock order.
LIFECYCLE_LOCK = 8023164291


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-controlled security deadlines."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class UserContext:
    """Carry a detached identity and the session reference, never a bearer credential."""

    profile: UserResponse
    session_id: int

    @property
    def id(self) -> int:
        """Return the stable internal account identifier."""
        return self.profile.id

    @property
    def roles(self) -> tuple[str, ...]:
        """Return explicit role codes verified for this request."""
        return self.profile.roles

    @property
    def permissions(self) -> tuple[str, ...]:
        """Return capabilities verified from the database for this request."""
        return self.profile.permissions


class AuthService:
    """Own complete transactions, including rechecking authorization before writes."""

    def __init__(
        self,
        session: AsyncSession,
        settings: AuthSettings,
        cipher: IdentityCipher,
        passwords: PasswordSecurity,
        mailer: InvitationMailer,
        clock: Callable[[], datetime] | None = None,
        name_search_cache: NameSearchCache | None = None,
    ) -> None:
        """Inject a request session, security resources, delivery boundary and testable clock."""
        self.db = session
        self.repo = AuthRepository(session)
        self.settings = settings
        self.cipher = cipher
        self.passwords = passwords
        self.mailer = mailer
        self.clock = clock or utc_now
        self.name_search_cache = (
            name_search_cache if name_search_cache is not None else NameSearchCache()
        )

    async def _lifecycle_lock(self) -> None:
        """Acquire the transaction-scoped PostgreSQL lock before taking account row locks."""
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LIFECYCLE_LOCK})

    def _active(self, user: User, now: datetime) -> bool:
        """Require active status, a password and an unexpired temporary bootstrap grant."""
        return bool(
            user.status == "active"
            and user.password_hash
            and (
                not user.is_bootstrap
                or (user.bootstrap_expires_at is not None and user.bootstrap_expires_at > now)
            )
        )

    def _valid_session(self, session: Session, now: datetime) -> bool:
        """Enforce independent absolute and inactivity deadlines on the server."""
        return (
            session.revoked_at is None
            and session.expires_at > now
            and session.last_activity_at + timedelta(seconds=self.settings.idle_seconds) > now
        )

    async def _profile(
        self,
        user: User,
        *,
        roles: tuple[str, ...] | None = None,
        permissions: tuple[str, ...] | None = None,
    ) -> UserResponse:
        """Decrypt only the response fields authorized by the calling service operation."""
        if roles is None and permissions is None:
            roles, permissions = await self.repo.grants(user.id)
        return UserResponse(
            id=user.id,
            username=self.cipher.decrypt(user.id, "username", user.username_encrypted),
            first_name=self.cipher.decrypt(user.id, "first_name", user.first_name_encrypted)
            if user.first_name_encrypted is not None
            else None,
            last_name=self.cipher.decrypt(user.id, "last_name", user.last_name_encrypted)
            if user.last_name_encrypted is not None
            else None,
            email=self.cipher.decrypt(user.id, "email", user.email_encrypted)
            if user.email_encrypted is not None
            else None,
            status=user.status,
            roles=await self.repo.roles(user.id) if roles is None else roles,
            permissions=await self.repo.permissions(user.id)
            if permissions is None
            else permissions,
            email_verified=user.email_verified_at is not None,
            is_bootstrap=user.is_bootstrap,
            created_at=user.created_at,
        )

    async def _actor(
        self, context: UserContext, *, admin: bool = False, permission: str | None = None
    ) -> User:
        """Recheck the actor and session under the user lock inside the mutation transaction."""
        user = await self.repo.user(context.id, lock=True)
        session = await self.db.get(Session, context.session_id, populate_existing=True)
        now = self.clock()
        if (
            user is None
            or not self._active(user, now)
            or session is None
            or session.user_id != user.id
            or not self._valid_session(session, now)
        ):
            raise AuthError(401, LOGIN_REQUIRED)
        if admin:
            permission = "users.manage"
        if permission and (
            user.is_bootstrap or permission not in await self.repo.permissions(user.id)
        ):
            raise AuthError(403, FORBIDDEN)
        return user

    async def _limit(self, scope: str, identity: str, ip: str) -> None:
        """Commit rate reservations even when the later authentication operation fails."""
        now = self.clock()
        # IP always precedes identity locks. Blocked IPs cannot grow the identity-key table.
        budgets = [
            (self.cipher.lookup(f"rate:{scope}:ip", ip), self.settings.login_ip_limit),
            (
                self.cipher.lookup(f"rate:{scope}:identity", identity),
                self.settings.login_identity_limit,
            ),
        ]
        blocked_until: datetime | None = None
        async with self.db.begin():
            for key, limit in budgets:
                attempts, expiry = await self.repo.reserve_attempt(
                    key, limit, now, self.settings.rate_window_seconds
                )
                if attempts > limit:
                    blocked_until = expiry
                    break
        if blocked_until:
            raise AuthError(
                429,
                "Trop de tentatives. Réessayez plus tard.",
                max(1, math.ceil((blocked_until - now).total_seconds())),
            )

    async def login(
        self,
        identifier: str,
        password: str,
        ip: str,
        previous_token: str | None = None,
    ) -> tuple[UserContext, str]:
        """Reserve capacity before lookup; only failed authentication consumes the IP budgets."""
        field = "email" if "@" in identifier else "username"
        try:
            normalized = (
                normalize_email(identifier) if field == "email" else normalize_username(identifier)
            )
        except ValueError:
            normalized = identifier.strip().lower()
        ip_key = self.cipher.lookup("rate:login:ip", ip)
        identity_key = self.cipher.lookup("rate:login:identity", f"{ip}\0{field}\0{normalized}")
        now = self.clock()
        async with self.db.begin():
            lease, blocked_until = await self.repo.reserve_login(
                ip_key,
                identity_key,
                self.settings.login_ip_limit,
                self.settings.login_identity_limit,
                now,
                self.settings.login_reservation_seconds,
            )
        if lease is None:
            async with self.db.begin():
                await record_login_failure(self.db, now, limited=True)
            raise AuthError(
                429,
                "Trop de tentatives. Réessayez plus tard.",
                max(1, math.ceil((blocked_until - now).total_seconds())),
            )
        failed = False
        try:
            return await self._login_reserved(field, normalized, password, previous_token)
        except AuthError as error:
            failed = error.status == 401
            raise
        finally:
            # Cancellation must not strand a live lease; crashed processes have bounded leases.
            with anyio.CancelScope(shield=True):
                async with self.db.begin():
                    await self.repo.finish_login(
                        lease,
                        failed=failed,
                        now=self.clock(),
                        seconds=self.settings.rate_window_seconds,
                    )
                    if failed:
                        await record_login_failure(self.db, self.clock(), limited=False)

    async def _login_reserved(
        self, field: str, normalized: str, password: str, previous_token: str | None
    ) -> tuple[UserContext, str]:
        """Verify a reserved login outside transactions, then atomically issue its session."""
        async with self.db.begin():
            candidate = await self.repo.by_lookup(field, self.cipher.lookup(field, normalized))
            candidate_id = candidate.id if candidate else None
            encoded = candidate.password_hash if candidate else None
        valid = await self.passwords.verify(encoded, password)
        if not valid or candidate_id is None:
            raise AuthError(401, LOGIN_FAILED)
        replacement = None
        if self.passwords.hasher.check_needs_rehash(encoded):
            replacement = await self.passwords.hash(password)
        token = new_token()
        async with self.db.begin():
            user = await self.repo.user(candidate_id, lock=True)
            now = self.clock()
            if user is None or not self._active(user, now) or user.password_hash != encoded:
                raise AuthError(401, LOGIN_FAILED)
            if replacement:
                user.password_hash = replacement
            if previous_token and TOKEN_PATTERN.fullmatch(previous_token):
                previous = await self.repo.session_by_hash(token_digest(previous_token))
                if previous and previous.user_id == user.id and previous.revoked_at is None:
                    previous.revoked_at = now
                    previous.revocation_reason = "replaced"
            duration = timedelta(seconds=self.settings.session_seconds)
            expiration = (
                min(now + duration, user.bootstrap_expires_at)
                if user.is_bootstrap
                else (now + duration)
            )
            session = Session(
                user_id=user.id,
                token_hash=token_digest(token),
                created_at=now,
                expires_at=expiration,
                last_activity_at=now,
            )
            self.db.add(session)
            await record_event(
                self.db, "auth.login_succeeded", user.id, subject_user_id=user.id, occurred_at=now
            )
            user.login_count += 1
            user.last_login_at = now
            user.updated_at = now
            context = UserContext(await self._profile(user), session.id)
        return context, token

    async def authenticate(self, token: str | None) -> UserContext:
        """Validate a bearer cookie and refresh one timestamp without recording navigation."""
        if not token or not TOKEN_PATTERN.fullmatch(token):
            raise AuthError(401, LOGIN_REQUIRED)
        async with self.db.begin():
            session = await self.repo.session_by_hash(token_digest(token))
            if session is None:
                raise AuthError(401, LOGIN_REQUIRED)
            user = await self.repo.user(session.user_id, lock=True)
            # Refresh after the lock: a concurrent revocation may have committed while waiting.
            await self.db.refresh(session)
            now = self.clock()
            if user is None or not self._active(user, now) or not self._valid_session(session, now):
                raise AuthError(401, LOGIN_REQUIRED)
            session.last_activity_at = now
            return UserContext(await self._profile(user), session.id)

    async def account(self, actor: UserContext) -> AccountResponse:
        """Return the caller's account timestamps and counters, never credential material."""
        async with self.db.begin():
            user = await self._actor(actor)
            profile = await self._profile(user)
            return AccountResponse(
                **profile.model_dump(),
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
                password_changed_at=user.password_changed_at,
                email_verified_at=user.email_verified_at,
                login_count=user.login_count,
            )

    async def logout(self, actor: UserContext) -> None:
        """Revoke only the current browser session while rechecking account activity."""
        async with self.db.begin():
            await self._actor(actor)
            session = await self.db.get(Session, actor.session_id)
            session.revoked_at = self.clock()
            session.revocation_reason = "logout"

    async def change_password(
        self,
        actor: UserContext,
        current: str,
        replacement: str,
        ip: str,
    ) -> None:
        """Verify the current password and revoke every session after an atomic replacement."""
        self._check_password(replacement)
        await self._limit("password", str(actor.id), ip)
        async with self.db.begin():
            user = await self._actor(actor)
            if user.is_bootstrap:
                raise AuthError(403, FORBIDDEN)
            encoded = user.password_hash
        if not await self.passwords.verify(encoded, current):
            raise AuthError(400, "Le mot de passe actuel est incorrect.")
        hashed = await self.passwords.hash(replacement)
        async with self.db.begin():
            user = await self._actor(actor)
            if user.password_hash != encoded:
                raise AuthError(401, LOGIN_REQUIRED)
            now = self.clock()
            user.password_hash = hashed
            user.password_changed_at = now
            user.updated_at = now
            await self.repo.revoke_sessions(user.id, now, "password_changed")

    @staticmethod
    def _check_password(password: str) -> None:
        """Translate password policy rejection without returning the supplied password."""
        try:
            validate_password(password)
        except ValueError:
            raise AuthError(
                422,
                "Utilisez 10 à 128 caractères ASCII, avec minuscule, majuscule, "
                "chiffre et ponctuation.",
            ) from None

    async def _create(self, data: CreateUserRequest, *, bootstrap: bool = False) -> User:
        """Encrypt identities and assign catalogue roles within the caller's transaction."""
        if data.promotion_ids and not can_join_promotion(data.roles):
            raise AuthError(
                422, "Seul un élève, un enseignant ou un khôlleur peut rejoindre une promotion."
            )
        roles = await self.repo.role_records(data.roles)
        if len(roles) != len(data.roles):
            raise AuthError(422, INVALID_REQUEST)
        now = self.clock()
        user_id = await self._next_user_id()
        username = await self._generate_username(data.first_name, data.last_name)
        user = User(
            id=user_id,
            username_encrypted=self.cipher.encrypt(user_id, "username", username),
            first_name_encrypted=self.cipher.encrypt(user_id, "first_name", data.first_name),
            last_name_encrypted=self.cipher.encrypt(user_id, "last_name", data.last_name),
            email_encrypted=self.cipher.encrypt(user_id, "email", data.email),
            username_lookup=self.cipher.lookup("username", username),
            email_lookup=self.cipher.lookup("email", data.email),
            status="pending_activation",
            is_bootstrap=bootstrap,
            login_count=0,
            created_at=now,
            updated_at=now,
            bootstrap_expires_at=(now + timedelta(seconds=self.settings.invitation_seconds))
            if bootstrap
            else None,
        )
        await self._insert_user(user)
        self.db.add_all([UserRole(user_id=user.id, role_id=role.id) for role in roles])
        await self.db.flush()
        if data.promotion_ids:
            promotions = list(
                (
                    await self.db.scalars(
                        select(Promotion)
                        .where(Promotion.id.in_(data.promotion_ids))
                        .order_by(Promotion.id)
                        .with_for_update()
                    )
                ).all()
            )
            if len(promotions) != len(data.promotion_ids) or any(
                not promotion.is_active for promotion in promotions
            ):
                raise AuthError(422, "Promotions inexistantes ou inactives.")
            self.db.add_all(
                UserPromotion(user_id=user.id, promotion_id=item.id) for item in promotions
            )
        return user

    async def _next_user_id(self) -> int:
        """Reserve an identity before encrypting fields bound to the account's integer ID."""
        return await self.db.scalar(
            text("SELECT nextval(pg_get_serial_sequence('sophikron.users', 'id'))")
        )

    async def _insert_user(self, user: User) -> None:
        """Insert an account whose sequence-generated identity was reserved for encryption."""
        self.db.add(user)
        await self.db.flush()

    async def _generate_username(self, first_name: str, last_name: str) -> str:
        """Randomly try each suffix at most once under the lifecycle transaction lock."""
        prefix = username_prefix(first_name, last_name)
        suffixes = list(range(100, 1000))
        secrets.SystemRandom().shuffle(suffixes)
        for suffix in suffixes:
            candidate = f"{prefix}{suffix}"
            if (
                await self.repo.by_lookup("username", self.cipher.lookup("username", candidate))
                is None
            ):
                return candidate
        raise AuthError(409, "Aucun identifiant disponible pour ce nom et ce prénom.")

    async def create_user(self, actor: UserContext, data: CreateUserRequest) -> UserResponse:
        """Create only an unactivated account; never accept an administrator-supplied password."""
        try:
            async with self.db.begin():
                await self._lifecycle_lock()
                admin = await self._actor(actor, admin=True)
                if admin.is_bootstrap:
                    raise AuthError(403, FORBIDDEN)
                user = await self._create(data)
                await record_event(
                    self.db,
                    "user.created",
                    admin.id,
                    subject_user_id=user.id,
                    data={"roles": data.roles},
                )
                for promotion_id in data.promotion_ids:
                    await record_event(
                        self.db,
                        "promotion.member_added",
                        admin.id,
                        subject_user_id=user.id,
                        resource_type="promotion",
                        resource_id=promotion_id,
                    )
                return await self._profile(user)
        except IntegrityError:
            raise AuthError(409, "Ce compte ne peut pas être créé avec ces informations.") from None

    async def _issue(
        self,
        user: User,
        issuer: int | None,
        delivery: str,
    ) -> tuple[AccountInvitation, str]:
        """Replace every unused link with a fresh verifier while holding the owner's lock."""
        now = self.clock()
        await self.repo.revoke_invitations(user.id, now)
        token = new_token()
        invitation = AccountInvitation(
            user_id=user.id,
            token_hash=token_digest(token),
            issued_by_user_id=issuer,
            issuance_kind="bootstrap" if issuer is None else "admin",
            delivery_method=delivery,
            purpose="reset" if user.status == "active" else "activation",
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.invitation_seconds),
        )
        self.db.add(invitation)
        await self.db.flush()
        await record_event(
            self.db,
            "invitation.issued",
            issuer,
            subject_user_id=user.id,
            data={"delivery": delivery, "purpose": invitation.purpose},
        )
        return invitation, token

    async def invite_manually(
        self, actor: UserContext, user_id: int, ip: str
    ) -> ManualInvitationResponse:
        """Issue an explicitly enabled manual invitation without verifying the recipient's email."""
        if not self.settings.manual_invitations_enabled:
            raise AuthError(403, FORBIDDEN)
        await self._limit("invite", str(user_id), ip)
        async with self.db.begin():
            await self._lifecycle_lock()
            admin = await self._actor(actor, admin=True)
            if admin.is_bootstrap:
                raise AuthError(403, FORBIDDEN)
            user = await self.repo.user(user_id, lock=True)
            if user is None:
                raise AuthError(404, "Compte introuvable.")
            if user.status not in {"pending_activation", "active"} or user.is_bootstrap:
                raise AuthError(409, INVALID_REQUEST)
            invitation, token = await self._issue(user, admin.id, "manual")
            return ManualInvitationResponse(token=token, expires_at=invitation.expires_at)

    async def invite(self, actor: UserContext, user_id: int, ip: str) -> None:
        """Commit before SMTP and revoke this link on failure, allowing explicit retry."""
        if not self.mailer.available:
            raise AuthError(503, "L’envoi est indisponible. Réessayez plus tard.")
        await self._limit("invite", str(user_id), ip)
        async with self.db.begin():
            await self._lifecycle_lock()
            admin = await self._actor(actor, admin=True)
            user = await self.repo.user(user_id, lock=True)
            if user is None:
                raise AuthError(404, "Compte introuvable.")
            if user.status not in {"pending_activation", "active"} or user.is_bootstrap:
                raise AuthError(409, INVALID_REQUEST)
            if admin.is_bootstrap and "admin" not in await self.repo.roles(user.id):
                raise AuthError(403, FORBIDDEN)
            invitation, token = await self._issue(user, admin.id, "email")
            recipient = self.cipher.decrypt(user.id, "email", user.email_encrypted)
        try:
            await self.mailer.send_invitation(recipient, token)
        except MailDeliveryError:
            async with self.db.begin():
                await self.repo.user(user_id, lock=True)
                await self.db.refresh(invitation)
                if invitation.used_at is None and invitation.revoked_at is None:
                    invitation.revoked_at = self.clock()
            raise AuthError(503, "L’envoi est indisponible. Réessayez plus tard.") from None

    async def activate(self, token: str, password: str, ip: str) -> None:
        """Consume an invitation atomically without an authenticated session."""
        await self._limit("activation", token_digest(token).hex(), ip)
        self._check_password(password)
        if not TOKEN_PATTERN.fullmatch(token):
            raise AuthError(400, INVALID_INVITATION)
        digest = token_digest(token)
        async with self.db.begin():
            candidate = await self.repo.invitation_by_hash(digest)
            now = self.clock()
            if candidate is None or (
                candidate.used_at is not None
                or candidate.revoked_at is not None
                or candidate.expires_at <= now
            ):
                raise AuthError(400, INVALID_INVITATION)
            user_id = candidate.user_id
        hashed = await self.passwords.hash(password)
        async with self.db.begin():
            await self._lifecycle_lock()
            user = await self.repo.user(user_id, lock=True)
            invitation = await self.repo.invitation_by_hash(digest)
            now = self.clock()
            if (
                user is None
                or user.status not in {"pending_activation", "active"}
                or invitation is None
                or invitation.used_at is not None
                or invitation.revoked_at is not None
                or invitation.expires_at <= now
                or (invitation.purpose == "activation" and user.status != "pending_activation")
                or (invitation.purpose == "reset" and user.status != "active")
                or (user.is_bootstrap and user.bootstrap_expires_at <= now)
            ):
                raise AuthError(400, INVALID_INVITATION)
            invitation.used_at = now
            user.password_hash = hashed
            user.status = "active"
            user.password_changed_at = now
            user.updated_at = now
            if invitation.delivery_method == "email":
                user.email_verified_at = now
            if invitation.purpose == "reset":
                await self.repo.revoke_sessions(user.id, now, "password_reset")
                await self.repo.revoke_invitations(user.id, now)
                await record_event(self.db, "auth.password_reset", user.id, subject_user_id=user.id)
            if not user.is_bootstrap and "admin" in await self.repo.roles(user.id):
                state = await self.db.get(ApplicationState, 1, with_for_update=True)
                if state.initialized_at is None:
                    state.initialized_at = now
                initial = await self.db.scalar(
                    select(User).where(User.is_bootstrap).with_for_update()
                )
                if initial and initial.status != "disabled":
                    initial.status = "disabled"
                    initial.password_hash = None
                    initial.updated_at = now
                    await self.repo.revoke_sessions(initial.id, now, "bootstrap_completed")
                    await self.repo.revoke_invitations(initial.id, now)

    async def access_invitation(
        self, actor: UserContext, user_id: int, ip: str
    ) -> AccessInvitationResponse:
        """Choose configured email delivery or return a manual link for activation/reset."""
        if self.mailer.available:
            await self.invite(actor, user_id, ip)
            async with self.db.begin():
                await self._actor(actor, admin=True)
                invitation = await self.db.scalar(
                    select(AccountInvitation).where(
                        AccountInvitation.user_id == user_id,
                        AccountInvitation.used_at.is_(None),
                        AccountInvitation.revoked_at.is_(None),
                    )
                )
                if invitation is None:
                    raise AuthError(409, INVALID_REQUEST)
                return AccessInvitationResponse(
                    delivery="email", purpose=invitation.purpose, expires_at=invitation.expires_at
                )
        await self._limit("invite", str(user_id), ip)
        async with self.db.begin():
            await self._lifecycle_lock()
            await self._actor(actor, admin=True)
            user = await self.repo.user(user_id, lock=True)
            if user is None or user.is_bootstrap:
                raise AuthError(404, "Compte introuvable.")
            if user.status not in {"active", "pending_activation"}:
                raise AuthError(409, "Réactivez ce compte avant de l’inviter.")
            invitation, token = await self._issue(user, actor.id, "manual")
            return AccessInvitationResponse(
                delivery="manual",
                purpose=invitation.purpose,
                expires_at=invitation.expires_at,
                token=token,
            )

    async def own_promotions(self, actor: UserContext) -> list[PromotionBadge]:
        """Read the authenticated account's own memberships without roster access."""
        async with self.db.begin():
            await self._actor(actor)
            promotions = (
                await self.db.scalars(
                    select(Promotion)
                    .join(UserPromotion)
                    .where(UserPromotion.user_id == actor.id)
                    .order_by(Promotion.year.desc(), Promotion.identifier)
                )
            ).all()
            return [
                PromotionBadge.model_validate(item, from_attributes=True) for item in promotions
            ]

    async def initialize_installation(self, *, renew: bool = False) -> bool:
        """Initialize once; only explicit local recovery may reset an unfinished bootstrap.

        Returns
        -------
        bool
            Whether a temporary administrator was created or explicitly renewed.
        """
        async with self.db.begin():
            state = await self.db.get(ApplicationState, 1)
            if state is None:
                raise RuntimeError("Installation state is missing; run the migrations first")
            if state.initialized_at is not None:
                if renew:
                    raise ValueError("The installation is already complete")
                return False
        if not self.settings.bootstrap_username:
            raise ValueError("AUTH_BOOTSTRAP_USERNAME is required before installation is complete")
        username = normalize_username(self.settings.bootstrap_username)
        # Read and hash only for a genuinely new setup or explicit local recovery.
        async with self.db.begin():
            existing = await self.db.scalar(select(User.id).where(User.is_bootstrap))
        if existing is not None and not renew:
            return False
        hashed = await self.passwords.hash(self.settings.bootstrap_password())
        async with self.db.begin():
            await self._lifecycle_lock()
            state = await self.db.get(ApplicationState, 1, with_for_update=True)
            if state.initialized_at is not None:
                if renew:
                    raise ValueError("The installation is already complete")
                return False
            initial = await self.db.scalar(select(User).where(User.is_bootstrap).with_for_update())
            if initial is None:
                if await self.db.scalar(select(User.id).limit(1)) is not None:
                    raise RuntimeError("Existing accounts require explicit installation recovery")
                now = self.clock()
                user_id = await self._next_user_id()
                initial = User(
                    id=user_id,
                    username_encrypted=self.cipher.encrypt(user_id, "username", username),
                    username_lookup=self.cipher.lookup("username", username),
                    email_encrypted=None,
                    email_lookup=None,
                    status="active",
                    password_hash=hashed,
                    is_bootstrap=True,
                    bootstrap_expires_at=now + timedelta(seconds=self.settings.invitation_seconds),
                    created_at=now,
                    updated_at=now,
                    password_changed_at=now,
                    login_count=0,
                )
                await self._insert_user(initial)
                roles = await self.repo.role_records(["admin"])
                if len(roles) != 1:
                    raise RuntimeError("The administrator role is missing")
                self.db.add(UserRole(user_id=user_id, role_id=roles[0].id))
            elif not renew:
                return False
            else:
                administrators = await self.db.scalars(
                    select(User).where(User.status == "active", User.is_bootstrap.is_(False))
                )
                for user in administrators:
                    if "admin" in await self.repo.roles(user.id):
                        raise AuthError(409, INVALID_REQUEST)
                now = self.clock()
                await self.repo.revoke_sessions(initial.id, now, "bootstrap_renewed")
                initial.username_encrypted = self.cipher.encrypt(initial.id, "username", username)
                initial.username_lookup = self.cipher.lookup("username", username)
                initial.status = "active"
                initial.password_hash = hashed
                initial.password_changed_at = now
                initial.bootstrap_expires_at = now + timedelta(
                    seconds=self.settings.invitation_seconds
                )
                initial.updated_at = now
                await self.repo.revoke_invitations(initial.id, now)
        return True

    async def complete_setup(
        self,
        actor: UserContext,
        data: CompleteSetupRequest,
        ip: str,
    ) -> UserResponse:
        """Atomically create the permanent administrator and retire every temporary credential."""
        self._check_password(data.password.get_secret_value())
        await self._limit("setup", str(actor.id), ip)
        async with self.db.begin():
            initial = await self._actor(actor)
            if not initial.is_bootstrap:
                raise AuthError(403, FORBIDDEN)
        hashed = await self.passwords.hash(data.password.get_secret_value())
        try:
            async with self.db.begin():
                await self._lifecycle_lock()
                initial = await self._actor(actor)
                state = await self.db.get(ApplicationState, 1, with_for_update=True)
                if not initial.is_bootstrap or state.initialized_at is not None:
                    raise AuthError(403, FORBIDDEN)
                permanent = await self._create(
                    CreateUserRequest(
                        first_name=data.first_name,
                        last_name=data.last_name,
                        email=data.email,
                        roles=["admin"],
                    )
                )
                now = self.clock()
                permanent.status = "active"
                permanent.password_hash = hashed
                permanent.password_changed_at = now
                initial.status = "disabled"
                initial.password_hash = None
                initial.updated_at = now
                state.initialized_at = now
                await self.repo.revoke_sessions(initial.id, now, "bootstrap_completed")
                await self.repo.revoke_invitations(initial.id, now)
                await self.db.flush()
                await record_event(
                    self.db,
                    "user.created",
                    initial.id,
                    subject_user_id=permanent.id,
                    data={"roles": ["admin"]},
                )
                return await self._profile(permanent)
        except IntegrityError:
            raise AuthError(409, "Ce compte ne peut pas être créé avec ces informations.") from None
