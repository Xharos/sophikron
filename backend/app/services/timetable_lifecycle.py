"""Apply the September rollover once, including catch-up after downtime."""

import asyncio
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.models import TimetableCalendar, TimetablePreferences, TimetableYear
from app.services.auth import LIFECYCLE_LOCK
from app.services.timetable_engine import PARIS, current_school_year


async def rollover(db: AsyncSession, today: date) -> TimetablePreferences:
    """Archive expired active calendars atomically under the shared lifecycle lock."""
    preferences = await db.get(TimetablePreferences, 1)
    year = current_school_year(today)
    if preferences is not None and (
        not preferences.auto_archive or (preferences.last_rollover_year or 0) >= year
    ):
        return preferences
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LIFECYCLE_LOCK})
    preferences = await db.get(TimetablePreferences, 1, populate_existing=True)
    if preferences is None:
        preferences = TimetablePreferences(id=1, auto_archive=True, revision=uuid4().hex)
        db.add(preferences)
        await db.flush()
    if not preferences.auto_archive or (preferences.last_rollover_year or 0) >= year:
        return preferences
    expired = list(
        await db.execute(
            select(TimetableCalendar, TimetableYear)
            .join(TimetableYear, TimetableYear.calendar_id == TimetableCalendar.id)
            .where(TimetableCalendar.is_archived.is_(False), TimetableYear.school_year < year)
        )
    )
    for calendar, annual in expired:
        calendar.is_archived, calendar.is_paused = True, True
        calendar.revision, annual.revision = uuid4().hex, uuid4().hex
        annual.updated_at = datetime.now(timezone.utc)
    preferences.last_rollover_year = year
    await db.flush()
    return preferences


async def timetable_maintenance(database: Database) -> None:
    """Check the local school date periodically without interrupting other maintenance."""
    while True:
        try:
            async with database.sessions() as db, db.begin():
                await rollover(db, datetime.now(PARIS).date())
        except Exception:
            logging.getLogger(__name__).exception("Timetable rollover failed; will retry")
        await asyncio.sleep(60)
