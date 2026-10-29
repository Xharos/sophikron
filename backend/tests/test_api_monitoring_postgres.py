"""Actual PostgreSQL monitoring UPSERT concurrency, retention and bounded JSON contracts."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models.statistics import ApiMetric
from app.services.api_monitoring import ApiMonitor
from tests.test_auth_postgres import Harness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_atomic_monitoring_reduction_retention_and_authorization(auth_case: Harness) -> None:
    """Reduce many minute rows in SQL, preserve exact code counts and reject non-admin reads."""
    case = auth_case
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    first, second = ApiMonitor(), ApiMonitor()
    for index in range(60):
        moment = now - timedelta(minutes=index)
        first.observe("other", 200, 1000, now=moment)
        second.observe("other", 503, 100000, now=moment)
    try:
        await asyncio.gather(first.flush(case.database), second.flush(case.database))
        assert not first.pending and not second.pending
        async with case.database.sessions() as session:
            row = await session.get(ApiMetric, (now, "other"))
            assert row.requests == 2 and row.statuses == {"200": 1, "503": 1}
            assert sum(row.histogram.values()) == 2
        case.as_admin()
        for period, maximum in (("day", 1500), ("week", 169), ("month", 30)):
            response = await case.client.get(
                f"/api/v1/admin/monitoring?period={period}&category=other"
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert len(body["points"]) <= maximum
            assert body["requests"] >= 2
            assert body["mean_ms"] == 50.5 and body["p95_ms"] == 100
            assert body["server_error_rate"] == 50
            point = next(point for point in body["points"] if point["requests"] > 0)
            detail = await case.client.get(
                "/api/v1/admin/monitoring",
                params={
                    "period": period,
                    "category": "other",
                    "interval": point["timestamp"],
                },
            )
            assert detail.status_code == 200, detail.text
            assert set(detail.json()["statuses"]) == {"200", "503"}
        assert (
            await case.client.get("/api/v1/admin/monitoring?category=SECRET")
        ).status_code == 422
        async with case.database.sessions.begin() as session:
            template = await session.get(ApiMetric, (now, "other"))
            fields = {
                column.name: getattr(template, column.name)
                for column in ApiMetric.__table__.columns
            }
            fields["bucket"] = now - timedelta(days=32)
            session.add(ApiMetric(**fields))
        await first.flush(case.database)
        async with case.database.sessions() as session:
            assert await session.get(ApiMetric, (now - timedelta(days=32), "other")) is None
        _, name = await case.create("teacher")
        from tests.test_calendar_subscriptions_postgres import login

        await login(case, name)
        assert (await case.client.get("/api/v1/admin/monitoring")).status_code == 403
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(ApiMetric).where(ApiMetric.category == "other"))
