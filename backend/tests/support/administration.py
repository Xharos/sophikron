"""Shared synthetic fixtures and helpers; never collected as tests."""

import os
from pathlib import Path

from sqlalchemy import delete

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models import (
    Promotion,
    PromotionAccountBlock,
    UserPromotion,
)
from tests.support.authentication import Harness


async def make_promotion(case: Harness, identifier: str = "PTSI") -> int:
    """Create a synthetic promotion and return its generated integer identity."""
    case.as_admin()
    response = await case.client.post(
        "/api/v1/admin/promotions",
        json={
            "year": 2019,
            "identifier": identifier,
            "color": "#123abc",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def clear_promotions(ids: list[int]) -> None:
    """Remove synthetic catalogue rows through the migration role after memberships are gone."""
    database = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    try:
        async with database.sessions.begin() as session:
            await session.execute(
                delete(PromotionAccountBlock).where(PromotionAccountBlock.promotion_id.in_(ids))
            )
            await session.execute(delete(UserPromotion).where(UserPromotion.promotion_id.in_(ids)))
            await session.execute(delete(Promotion).where(Promotion.id.in_(ids)))
    finally:
        await database.close()
