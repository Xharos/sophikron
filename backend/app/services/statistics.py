"""Authorized dashboard assembly, Paris date windows and private storage inspection."""

import os
import stat
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import anyio
from sqlalchemy import Integer, Select, cast, func, select

from app.core.documents import DocumentSettings
from app.models import (
    ActivityEvent,
    Lesson,
    LessonCollaborator,
    Promotion,
    Role,
    User,
    UserPromotion,
    UserRole,
)
from app.models.lessons import LessonElement, LessonFile, LessonFileDeletion, LessonUpload
from app.models.site import Subject
from app.models.statistics import CalendarUsageTotal, LoginStatistic
from app.models.timetable import TimetableSubscription
from app.repositories.statistics import StatisticsRepository
from app.schemas.statistics import Breakdown, Period, StatisticsResponse, StorageStatistics
from app.services.auth import AuthService, UserContext
from app.services.calendar_subscriptions import calendar_eligibility
from app.services.errors import AuthError

PARIS = ZoneInfo("Europe/Paris")


def statistics_window(now: datetime, period: Period) -> tuple[datetime, list[datetime]]:
    """Build complete Paris calendar bins, preserving both repeated autumn hours.

    Parameters
    ----------
    now
        Aware current instant.
    period
        Today, seven inclusive calendar days or thirty inclusive calendar days.

    Returns
    -------
    tuple
        UTC window start and UTC bucket instants, including the current partial bucket.
    """
    today = now.astimezone(PARIS).date()
    days = {"day": 1, "week": 7, "month": 30}[period]
    start = datetime.combine(today - timedelta(days=days - 1), time(), PARIS).astimezone(UTC)
    if period == "day":
        stop = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        bins = [
            start + timedelta(hours=index)
            for index in range(int((stop - start).total_seconds() / 3600))
        ]
    else:
        bins = [
            datetime.combine(today - timedelta(days=days - 1 - index), time(), PARIS).astimezone(
                UTC
            )
            for index in range(days)
        ]
    return start, bins


def folder_usage(settings: DocumentSettings) -> tuple[int | None, int | None]:
    """Count regular files in managed folders without following symbolic links.

    Parameters
    ----------
    settings
        Private document root; filesystem-wide used space is deliberately not a document metric.

    Returns
    -------
    tuple
        Object and temporary byte counts, or unavailable values on storage errors.
    """
    sizes = []
    try:
        if settings.root.is_symlink():
            return None, None
        for name in ("objects", "temporary"):
            folder = settings.root / name
            if folder.is_symlink():
                return None, None
            total = 0
            if folder.exists():
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            facts = entry.stat(follow_symlinks=False)
                            if stat.S_ISREG(facts.st_mode):
                                total += facts.st_size
                        except FileNotFoundError:
                            continue
            sizes.append(total)
        return sizes[0], sizes[1]
    except OSError:
        return None, None


class StatisticsService:
    """Authorize scope with live grants before querying any course or account aggregates."""

    def __init__(self, auth: AuthService, settings: DocumentSettings) -> None:
        """Reuse request-owned database resources and configured document quotas."""
        self.auth, self.db, self.settings = auth, auth.db, settings
        self.repo = StatisticsRepository(self.db)

    async def read(
        self, actor: UserContext, period: Period, lesson_id: int | None = None
    ) -> StatisticsResponse:
        """Build global administrator, author-only or explicitly affiliated course statistics.

        Parameters
        ----------
        actor
            Session revalidated inside this read transaction.
        period
            Bounded calendar window.
        lesson_id
            Optional explicit course, requiring authorship, responsibility or current collaboration.

        Returns
        -------
        StatisticsResponse
            Aggregated values only; never individual download histories or student identities.
        """
        now = self.auth.clock()
        start, bins = statistics_window(now, period)
        async with self.db.begin():
            principal = await self.auth._actor(actor)
            permissions = await self.auth.repo.permissions(actor.id)
            if principal.is_bootstrap:
                raise AuthError(403, "Accès réservé aux comptes permanents.")
            admin = "statistics.read" in permissions
            teacher = "teacher.access" in permissions
            reader = "kholleur.access" in permissions
            courses = select(Lesson.id)
            scope = "admin" if admin else "author"
            if lesson_id is not None:
                lesson = await self.db.get(Lesson, lesson_id)
                if lesson is None:
                    raise AuthError(404, "Cours introuvable.")
                affiliated = await self.db.get(LessonCollaborator, (lesson_id, actor.id))
                allowed = (
                    admin
                    or (teacher and actor.id in {lesson.creator_id, lesson.responsible_id})
                    or ((teacher or reader) and affiliated is not None)
                )
                if not allowed:
                    raise AuthError(403, "Vous n’avez pas accès aux statistiques de ce cours.")
                courses = courses.where(Lesson.id == lesson_id)
                scope = "course"
            elif not admin:
                if not teacher:
                    raise AuthError(
                        403, "Statistiques réservées aux administrateurs et enseignants."
                    )
                courses = courses.where(Lesson.creator_id == actor.id)
            response = StatisticsResponse(
                scope=scope,
                period=period,
                timestamps=bins,
                generated_at=now,
                series={},
                totals={},
                storage=StorageStatistics(),
            )
            facts, total, unique = await self.repo.activity(
                "lesson.file_downloaded",
                start,
                now,
                hourly=period == "day",
                courses=None if scope == "admin" else courses,
            )
            self.fill_series(response, "downloads", "downloaders", facts, total, unique)
            await self.storage(response, courses, global_scope=scope == "admin")
            await self.rankings(response, courses, start, now, lesson_id)
            if scope == "admin":
                facts, total, unique = await self.repo.activity(
                    "auth.login_succeeded", start, now, hourly=period == "day"
                )
                self.fill_series(response, "logins", "unique_logins", facts, total, unique)
                await self.authentication(response, start, now)
                await self.catalogues(response)
                await self.calendar_usage(response, start, now)
            # Only administrator-wide statistics inspect the physical volume, outside SQL below.
        if scope == "admin":
            physical, temporary = await anyio.to_thread.run_sync(folder_usage, self.settings)
            response.storage.physical_bytes = physical
            response.storage.temporary_bytes = temporary
        return response

    async def calendar_usage(
        self, response: StatisticsResponse, start: datetime, now: datetime
    ) -> None:
        """Count current links and recent owners without disclosing secrets or poll histories."""
        eligible = (
            User.status == "active",
            User.password_hash.is_not(None),
            User.login_count > 0,
            ~User.is_bootstrap,
            TimetableSubscription.revoked_at.is_(None),
            TimetableSubscription.user_id.is_not(None),
            calendar_eligibility(now.astimezone(PARIS).date()),
        )
        total, recent = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count().filter(
                        TimetableSubscription.last_requested_at >= start,
                        TimetableSubscription.last_requested_at <= now,
                    ),
                )
                .select_from(User)
                .join(TimetableSubscription)
                .where(*eligible)
            )
        ).one()
        response.calendar_recent_users = recent
        response.calendar_eligible_users = total
        response.calendar_subscriptions = [
            Breakdown(label="Consulté", value=recent),
            Breakdown(label="Non consulté sur la période", value=total - recent),
        ]
        response.calendar_requests_total = (
            await self.db.scalar(
                select(CalendarUsageTotal.requests).where(CalendarUsageTotal.id == 1)
            )
            or 0
        )

    def fill_series(
        self,
        response: StatisticsResponse,
        total_key: str,
        unique_key: str,
        rows: list,
        total: int,
        unique: int,
    ) -> None:
        """Fill missing buckets with zero while keeping period-wide distinct totals independent."""
        values = {int(row[0].timestamp()): (int(row[1]), int(row[2])) for row in rows}
        response.series[total_key] = [
            values.get(int(item.timestamp()), (0, 0))[0] for item in response.timestamps
        ]
        response.series[unique_key] = [
            values.get(int(item.timestamp()), (0, 0))[1] for item in response.timestamps
        ]
        response.totals[total_key], response.totals[unique_key] = int(total), int(unique)

    async def authentication(
        self, response: StatisticsResponse, start: datetime, now: datetime
    ) -> None:
        """Combine recorded successes with anonymous failures; disclose historical coverage."""
        response.attempts_since = await self.db.scalar(
            select(func.min(LoginStatistic.tracked_from))
        )
        bucket = func.date_trunc(
            "hour" if response.period == "day" else "day",
            LoginStatistic.bucket,
            "UTC" if response.period == "day" else "Europe/Paris",
        )
        rows = (
            await self.db.execute(
                select(bucket, func.sum(LoginStatistic.failed), func.sum(LoginStatistic.limited))
                .where(LoginStatistic.bucket >= start, LoginStatistic.bucket <= now)
                .group_by(bucket)
            )
        ).all()
        self.fill_series(
            response,
            "failures",
            "limited",
            list(rows),
            sum(row[1] for row in rows),
            sum(row[2] for row in rows),
        )
        response.series["attempts"] = [
            a + b + c
            for a, b, c in zip(
                response.series["logins"],
                response.series["failures"],
                response.series["limited"],
                strict=True,
            )
        ]
        response.totals["attempts"] = sum(
            response.totals[key] for key in ("logins", "failures", "limited")
        )

    async def storage(
        self, response: StatisticsResponse, courses: Select[tuple[int]], *, global_scope: bool
    ) -> None:
        """Aggregate current published metadata and valid reservations in the authorized scope."""
        files = LessonFile.lesson_id.in_(courses)
        count, size = (
            await self.db.execute(
                select(func.count(), func.coalesce(func.sum(LessonFile.size_bytes), 0)).where(files)
            )
        ).one()
        formats = (
            await self.db.execute(
                select(LessonFile.extension, func.sum(LessonFile.size_bytes), func.count())
                .where(files)
                .group_by(LessonFile.extension)
                .order_by(LessonFile.extension)
            )
        ).all()
        reserved = await self.db.scalar(
            select(func.coalesce(func.sum(LessonUpload.size_bytes), 0)).where(
                LessonUpload.lesson_id.in_(courses), LessonUpload.expires_at > response.generated_at
            )
        )
        response.storage = StorageStatistics(
            files=count,
            bytes=size,
            reserved_bytes=reserved,
            quota_bytes=self.settings.total_quota_bytes
            if global_scope
            else (self.settings.course_quota_bytes if response.scope == "course" else 0),
            formats=[
                Breakdown(label=row[0].upper(), value=row[1], count=row[2]) for row in formats
            ],
            pending_deletions=await self.db.scalar(
                select(func.count()).select_from(LessonFileDeletion)
            )
            if global_scope
            else None,
        )

    async def rankings(
        self,
        response: StatisticsResponse,
        courses: Select[tuple[int]],
        start: datetime,
        end: datetime,
        lesson_id: int | None,
    ) -> None:
        """Rank scoped download counts; deleted resources retain totals but expose no stale name."""
        events = (
            select(ActivityEvent)
            .where(
                ActivityEvent.event_type == "lesson.file_downloaded",
                ActivityEvent.resource_id.in_(courses),
                ActivityEvent.occurred_at >= start,
                ActivityEvent.occurred_at < end,
            )
            .subquery()
        )
        if lesson_id is not None:
            rows = (
                await self.db.execute(
                    select(LessonFile.id, LessonElement.title, func.count())
                    .join(LessonElement, LessonElement.id == LessonFile.element_id)
                    .join(events, cast(events.c.data["file_id"].astext, Integer) == LessonFile.id)
                    .where(LessonFile.lesson_id.in_(courses))
                    .group_by(LessonFile.id, LessonElement.title)
                    .order_by(func.count().desc(), LessonFile.id)
                    .limit(5)
                )
            ).all()
        else:
            rows = (
                await self.db.execute(
                    select(Lesson.id, Lesson.title, func.count())
                    .join(events, events.c.resource_id == Lesson.id)
                    .where(Lesson.id.in_(courses))
                    .group_by(Lesson.id)
                    .order_by(func.count().desc(), Lesson.id)
                    .limit(5)
                )
            ).all()
        response.popular = [Breakdown(id=row[0], label=row[1], value=row[2]) for row in rows]
        if response.scope == "author":
            response.courses = [
                Breakdown(id=row.id, label=row.title, value=0)
                for row in await self.db.scalars(
                    select(Lesson)
                    .where(Lesson.id.in_(courses))
                    .order_by(Lesson.title_key)
                    .limit(100)
                )
            ]

    async def catalogues(self, response: StatisticsResponse) -> None:
        """Return role-aware counts, promotion effectifs and course counts per subject."""
        statuses = dict(
            (
                await self.db.execute(
                    select(User.status, func.count())
                    .where(~User.is_bootstrap)
                    .group_by(User.status)
                )
            ).all()
        )
        response.accounts = [
            Breakdown(label=label, value=statuses.get(key, 0))
            for key, label in (
                ("active", "Actifs"),
                ("pending_activation", "À activer"),
                ("disabled", "Archivés"),
            )
        ]
        role_rows = dict(
            (
                await self.db.execute(
                    select(Role.code, func.count())
                    .join(UserRole)
                    .join(User, User.id == UserRole.user_id)
                    .where(~User.is_bootstrap)
                    .group_by(Role.code)
                )
            ).all()
        )
        response.roles = [
            Breakdown(label=label, value=role_rows.get(key, 0))
            for key, label in (
                ("user", "Élèves"),
                ("teacher", "Enseignants"),
                ("kholleur", "Khôlleurs"),
                ("admin", "Administrateurs"),
            )
        ]
        pupil = select(UserRole.user_id).join(Role).where(Role.code == "user").subquery()
        staff = (
            select(UserRole.user_id)
            .join(Role)
            .where(Role.code.in_(["teacher", "kholleur"]))
            .subquery()
        )
        for student in (True, False):
            rows = (
                await self.db.execute(
                    select(
                        Promotion.id,
                        Promotion.identifier,
                        Promotion.year,
                        func.count(UserPromotion.user_id),
                    )
                    .outerjoin(
                        UserPromotion,
                        (UserPromotion.promotion_id == Promotion.id)
                        & (
                            UserPromotion.user_id.in_(select(pupil.c.user_id))
                            if student
                            else UserPromotion.user_id.in_(select(staff.c.user_id))
                        ),
                    )
                    .where(Promotion.is_active)
                    .group_by(Promotion.id)
                    .order_by(Promotion.year.desc(), Promotion.identifier)
                    .limit(8)
                )
            ).all()
            values = [
                Breakdown(id=row[0], label=f"{row[2]} · {row[1]}", value=row[3]) for row in rows
            ]
            if student:
                response.promotions = values
            else:
                response.promotion_staff = values
        rows = (
            await self.db.execute(
                select(Subject.id, Subject.name, func.count(Lesson.id))
                .outerjoin(Lesson, Lesson.subject_id == Subject.id)
                .where(Subject.is_active)
                .group_by(Subject.id)
                .order_by(func.count(Lesson.id).desc(), Subject.name)
                .limit(8)
            )
        ).all()
        response.subjects = [Breakdown(id=row[0], label=row[1], value=row[2]) for row in rows]
