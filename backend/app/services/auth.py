"""Atomic account lifecycle and server-side authentication rules."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import anyio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_config import AuthSettings
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
from app.models import AccountInvitation, ApplicationState, LoginEvent, Session, User, UserRole
from app.repositories.auth import AuthRepository
from app.schemas.auth import CompleteSetupRequest, CreateUserRequest, UserResponse
from app.services.errors import (
    FORBIDDEN,
    INVALID_INVITATION,
    INVALID_REQUEST,
    LOGIN_FAILED,
    LOGIN_REQUIRED,
    AuthError,
)
from app.services.mail import InvitationMailer, MailDeliveryError

# Serialize rare multi-account lifecycle operations in a consistent lock order.
LIFECYCLE_LOCK = 8023164291


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-controlled security deadlines."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class UserContext:
    """Carry a detached identity and the session reference, never a bearer credential."""

    profile: UserResponse
    session_id: UUID

    @property
    def id(self) -> UUID:
        """Return the stable internal account identifier."""
        return self.profile.id

    @property
    def roles(self) -> tuple[str, ...]:
        """Return explicit role codes verified for this request."""
        return self.profile.roles


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
    ) -> None:
        """Inject a request session, security resources, delivery boundary and testable clock."""
        self.db = session
        self.repo = AuthRepository(session)
        self.settings = settings
        self.cipher = cipher
        self.passwords = passwords
        self.mailer = mailer
        self.clock = clock or utc_now

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

    async def _profile(self, user: User) -> UserResponse:
        """Decrypt only the response fields authorized by the calling service operation."""
        return UserResponse(
            id=user.id,
            username=self.cipher.decrypt(user.id, "username", user.username_encrypted),
            email=self.cipher.decrypt(user.id, "email", user.email_encrypted)
            if user.email_encrypted is not None
            else None,
            status=user.status,
            roles=await self.repo.roles(user.id),
            email_verified=user.email_verified_at is not None,
            is_bootstrap=user.is_bootstrap,
            created_at=user.created_at,
        )

    async def _actor(self, context: UserContext, *, admin: bool = False) -> User:
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
        if admin and "admin" not in await self.repo.roles(user.id):
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
                        lease, failed=failed, now=self.clock(),
                        seconds=self.settings.rate_window_seconds,
                    )

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
                id=uuid4(),
                user_id=user.id,
                token_hash=token_digest(token),
                created_at=now,
                expires_at=expiration,
                last_activity_at=now,
            )
            self.db.add(session)
            self.db.add(LoginEvent(user_id=user.id, occurred_at=now))
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
        roles = await self.repo.role_records(data.roles)
        if len(roles) != len(data.roles):
            raise AuthError(422, INVALID_REQUEST)
        now = self.clock()
        user_id = uuid4()
        user = User(
            id=user_id,
            username_encrypted=self.cipher.encrypt(user_id, "username", data.username),
            email_encrypted=self.cipher.encrypt(user_id, "email", data.email),
            username_lookup=self.cipher.lookup("username", data.username),
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
        self.db.add(user)
        await self.db.flush()
        self.db.add_all([UserRole(user_id=user.id, role_id=role.id) for role in roles])
        await self.db.flush()
        return user

    async def create_user(self, actor: UserContext, data: CreateUserRequest) -> UserResponse:
        """Create only an unactivated account; never accept an administrator-supplied password."""
        try:
            async with self.db.begin():
                await self._lifecycle_lock()
                admin = await self._actor(actor, admin=True)
                if admin.is_bootstrap:
                    raise AuthError(403, FORBIDDEN)
                return await self._profile(await self._create(data))
        except IntegrityError:
            raise AuthError(409, "Ce compte ne peut pas être créé avec ces informations.") from None

    async def _issue(
        self,
        user: User,
        issuer: UUID | None,
        delivery: str,
    ) -> tuple[AccountInvitation, str]:
        """Replace every unused link with a fresh verifier while holding the owner's lock."""
        now = self.clock()
        await self.repo.revoke_invitations(user.id, now)
        token = new_token()
        invitation = AccountInvitation(
            id=uuid4(),
            user_id=user.id,
            token_hash=token_digest(token),
            issued_by_user_id=issuer,
            issuance_kind="bootstrap" if issuer is None else "admin",
            delivery_method=delivery,
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.invitation_seconds),
        )
        self.db.add(invitation)
        await self.db.flush()
        return invitation, token

    async def invite(self, actor: UserContext, user_id: UUID, ip: str) -> None:
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
            if user.status != "pending_activation" or user.is_bootstrap:
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
                or user.status != "pending_activation"
                or invitation is None
                or invitation.used_at is not None
                or invitation.revoked_at is not None
                or invitation.expires_at <= now
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
                user_id = uuid4()
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
                self.db.add(initial)
                await self.db.flush()
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
            initial = await self._actor(actor, admin=True)
            if not initial.is_bootstrap:
                raise AuthError(403, FORBIDDEN)
        hashed = await self.passwords.hash(data.password.get_secret_value())
        try:
            async with self.db.begin():
                await self._lifecycle_lock()
                initial = await self._actor(actor, admin=True)
                state = await self.db.get(ApplicationState, 1, with_for_update=True)
                if not initial.is_bootstrap or state.initialized_at is not None:
                    raise AuthError(403, FORBIDDEN)
                permanent = await self._create(
                    CreateUserRequest(
                        username=data.username,
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
                return await self._profile(permanent)
        except IntegrityError:
            raise AuthError(409, "Ce compte ne peut pas être créé avec ces informations.") from None
