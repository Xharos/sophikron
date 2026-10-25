"""Read-only student directory scoped in SQL to the teacher's shared promotions."""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from app.models import Promotion, User, UserPromotion
from app.schemas.administration import PromotionPage, SearchResult, StudentPage, StudentResponse
from app.services.administration import AdministrationService
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError


class TeachingService:
    """Reuse promotion presentation and matching without granting global directory access."""

    def __init__(self, auth: AuthService) -> None:
        """Share request-scoped resources while enforcing a distinct read capability."""
        self.auth = auth
        self.db = auth.db
        self.dashboard = AdministrationService(auth)

    def students_statement(self, teacher_id: int, promotion_id: int | None) -> Select[tuple[User]]:
        """Select students, including archived accounts, sharing a teacher membership."""
        teacher = aliased(UserPromotion)
        memberships = (
            select(UserPromotion.user_id)
            .join(teacher, teacher.promotion_id == UserPromotion.promotion_id)
            .where(teacher.user_id == teacher_id, UserPromotion.user_id == User.id)
        )
        if promotion_id is not None:
            memberships = memberships.where(UserPromotion.promotion_id == promotion_id)
        return self.dashboard.repo.users_statement(
            role="user", status=None, promotion_id=None
        ).where(memberships.exists())

    async def require_promotion(self, actor_id: int, promotion_id: int) -> None:
        """Hide unrelated promotion existence rather than exposing its members."""
        if await self.db.get(UserPromotion, (actor_id, promotion_id)) is None:
            raise AuthError(404, "Promotion introuvable.")

    def student_profile(self, user: User) -> StudentResponse:
        """Decrypt only identity fields needed for the teacher's student view."""
        cipher = self.auth.cipher
        return StudentResponse(
            id=user.id,
            username=cipher.decrypt(user.id, "username", user.username_encrypted),
            first_name=cipher.decrypt(user.id, "first_name", user.first_name_encrypted),
            last_name=cipher.decrypt(user.id, "last_name", user.last_name_encrypted),
            status=user.status,
            created_at=user.created_at,
        )

    async def promotions(
        self,
        actor: UserContext,
        *,
        offset: int,
        limit: int,
        q: str | None = None,
        is_active: bool | None = None,
    ) -> PromotionPage:
        """List only the caller's assigned promotions, including archives when requested."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="teaching.read")
            statement = (
                select(Promotion).join(UserPromotion).where(UserPromotion.user_id == actor.id)
            )
            if is_active is not None:
                statement = statement.where(Promotion.is_active == is_active)
            if q:
                escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(Promotion.identifier.ilike(f"%{escaped}%", escape="\\"))
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            promotions = list(
                (
                    await self.db.scalars(
                        statement.order_by(Promotion.year.desc(), Promotion.id)
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return PromotionPage(
                items=await self.dashboard._promotion_profiles(promotions),
                total=total,
                offset=offset,
                limit=limit,
            )

    async def students(
        self, actor: UserContext, *, promotion_id: int | None, offset: int, limit: int
    ) -> StudentPage:
        """Return a bounded student page after rechecking the teacher's current scope."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="teaching.read")
            if promotion_id is not None:
                await self.require_promotion(actor.id, promotion_id)
            statement = self.students_statement(actor.id, promotion_id)
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            users = (
                await self.db.scalars(statement.order_by(User.id).offset(offset).limit(limit))
            ).all()
            return StudentPage(
                items=[self.student_profile(user) for user in users],
                total=total,
                offset=offset,
                limit=limit,
            )

    async def student(self, actor: UserContext, user_id: int) -> StudentResponse:
        """Return a student's identity and only the promotions shared with this teacher."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="teaching.read")
            user = await self.db.scalar(
                self.students_statement(actor.id, None).where(User.id == user_id)
            )
            if user is None:
                raise AuthError(404, "Élève introuvable.")
            teacher = aliased(UserPromotion)
            promotions = list(
                (
                    await self.db.scalars(
                        select(Promotion)
                        .join(UserPromotion)
                        .join(teacher, teacher.promotion_id == Promotion.id)
                        .where(UserPromotion.user_id == user_id, teacher.user_id == actor.id)
                        .order_by(Promotion.year.desc(), Promotion.id)
                    )
                ).all()
            )
            result = self.student_profile(user)
            result.promotions = await self.dashboard._promotion_profiles(promotions)
            return result

    async def search(
        self, actor: UserContext, query: str, *, promotion_id: int | None, limit: int
    ) -> list[SearchResult]:
        """Reuse name/username matching only after selecting students inside teacher scope."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="teaching.read")
            if promotion_id is not None:
                await self.require_promotion(actor.id, promotion_id)
            rows = (
                await self.db.execute(
                    self.students_statement(actor.id, promotion_id).with_only_columns(
                        User.id,
                        User.first_name_encrypted,
                        User.last_name_encrypted,
                        User.username_encrypted,
                        User.status,
                    )
                )
            ).all()
        return await self.dashboard.match_search(rows, query, limit)
