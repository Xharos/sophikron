"""Privileged cleanup for synthetic records in the explicitly disposable test database."""

import os
from pathlib import Path

from sqlalchemy import delete, or_

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models import ActivityEvent


async def clear_test_events(ids: list[int]) -> None:
    """Remove only synthetic account events using the migration role, never runtime DML."""
    if os.environ.get("DB_INTEGRATION") != "1" or os.environ.get("DB_NAME") != "sophikron_test":
        raise ValueError("Dedicated disposable database required")
    database = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    try:
        async with database.sessions.begin() as session:
            await session.execute(
                delete(ActivityEvent).where(
                    or_(
                        ActivityEvent.actor_user_id.in_(ids), ActivityEvent.subject_user_id.in_(ids)
                    )
                )
            )
    finally:
        await database.close()
