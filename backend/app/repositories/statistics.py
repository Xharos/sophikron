"""Parameterized PostgreSQL aggregates, scoped before grouping or ranking."""

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityEvent, User


class StatisticsRepository:
    """Keep timestamp grouping and distinct counts in PostgreSQL, not browser approximations."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the caller-owned business transaction."""
        self.db = session

    async def activity(
        self,
        event_type: str,
        start: datetime,
        end: datetime,
        *,
        hourly: bool,
        courses: Select[tuple[int]] | None = None,
    ) -> tuple[list[tuple[datetime, int, int]], int, int]:
        """Return bucket totals and period-wide unique recipients after applying scope.

        Parameters
        ----------
        event_type
            Trusted event catalogue code.
        start, end
            Inclusive start and exclusive end of the requested window.
        hourly
            Use UTC hours for today, Paris calendar days for longer periods.
        courses
            Authorized lesson ID query, or None for administrator-wide access.

        Returns
        -------
        tuple
            Bucket rows, total transfers/logins and distinct accounts over the whole window.
        """
        timestamp = ActivityEvent.occurred_at
        base = (
            select(ActivityEvent.id, ActivityEvent.actor_user_id, timestamp)
            .join(User, User.id == ActivityEvent.actor_user_id)
            .where(
                ActivityEvent.event_type == event_type,
                timestamp >= start,
                timestamp < end,
                User.is_bootstrap.is_(False),
            )
        )
        if courses is not None:
            base = base.where(ActivityEvent.resource_id.in_(courses))
        facts = base.subquery()
        bucket = func.date_trunc(
            "hour" if hourly else "day",
            facts.c.occurred_at,
            "UTC" if hourly else "Europe/Paris",
        )
        rows = (
            await self.db.execute(
                select(bucket, func.count(), func.count(func.distinct(facts.c.actor_user_id)))
                .group_by(bucket)
                .order_by(bucket)
            )
        ).all()
        total, unique = (
            await self.db.execute(
                select(func.count(), func.count(func.distinct(facts.c.actor_user_id))).select_from(
                    facts
                )
            )
        ).one()
        return list(rows), total, unique
