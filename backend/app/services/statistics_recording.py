"""Small transactional writers shared by authentication and document transfers."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statistics import LoginStatistic


async def record_login_failure(session: AsyncSession, now: datetime, *, limited: bool) -> None:
    """Increment an anonymous hourly bucket atomically in the caller's transaction.

    Parameters
    ----------
    session
        Transaction owning the authentication outcome.
    now
        Outcome timestamp; UTC buckets preserve both hours at autumn clock changes.
    limited
        Distinguish rate-limited requests from credential failures.
    """
    bucket = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    statement = insert(LoginStatistic).values(
        bucket=bucket, failed=int(not limited), limited=int(limited), tracked_from=now
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[LoginStatistic.bucket],
            set_={
                "failed": LoginStatistic.failed + statement.excluded.failed,
                "limited": LoginStatistic.limited + statement.excluded.limited,
            },
        )
    )
