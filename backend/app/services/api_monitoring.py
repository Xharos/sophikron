"""Bounded anonymous minute aggregates, buffered writes and server-side chart reduction."""

import asyncio
import logging
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from time import perf_counter_ns

from sqlalchemy import delete, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.database import Database
from app.models.statistics import ApiMetric
from app.schemas.statistics import Period
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.statistics import PARIS, statistics_window

CATEGORIES = {
    "auth": "Authentification",
    "timetable_read": "Lecture des emplois du temps",
    "timetable_check": "Vérifications des emplois du temps",
    "timetable_write": "Modification des séances",
    "ics": "Export ICS",
    "administration": "Administration",
    "documents": "Documents",
    "statistics": "Statistiques",
    "other": "Autres",
}


def monitoring_timestamps(now: datetime, period: Period) -> list[datetime]:
    """Return chart intervals, covering the full Paris day for the daily view.

    Parameters
    ----------
    now, period
        Aware current instant and selected chart period.

    Returns
    -------
    list[datetime]
        UTC bucket starts; future daily buckets have no recorded measurements.
    """
    start, _ = statistics_window(now, period)
    unit = {"day": "minute", "week": "hour", "month": "day"}[period]
    end = (start.astimezone(PARIS) + timedelta(days=1)).astimezone(UTC) if period == "day" else now
    timestamps = []
    cursor = start.astimezone(UTC)
    while cursor < end if period == "day" else cursor <= end:
        timestamps.append(cursor)
        cursor = (
            (cursor.astimezone(PARIS) + timedelta(days=1)).astimezone(UTC)
            if unit == "day"
            else cursor + timedelta(**{unit + "s": 1})
        )
    return timestamps


# Noncumulative finite upper bounds in microseconds; the final bucket is overflow.
BOUNDS = (
    1000,
    5000,
    10000,
    25000,
    50000,
    100000,
    250000,
    500000,
    1000000,
    2000000,
    5000000,
    10000000,
    30000000,
)
ADDITIVE = (
    "requests",
    "duration_us",
    "successes",
    "redirects",
    "client_errors",
    "server_errors",
    "incomplete",
    "ics_refused",
)


def category_for(path: str, method: str) -> str:
    """Use nine fixed categories, never attacker-controlled paths or credential labels."""
    if path.startswith("/api/v1/timetable/feed/"):
        return "ics"
    if path.startswith("/api/v1/auth/"):
        return "auth"
    if "statistics" in path or path.startswith("/api/v1/admin/monitoring"):
        return "statistics"
    if path.startswith("/api/v1/timetable/"):
        if path.endswith(("/preview", "/diagnostics")):
            return "timetable_check"
        return "timetable_read" if method in {"GET", "HEAD"} else "timetable_write"
    if path.startswith("/api/v1/lessons"):
        return "documents"
    if path.startswith(
        ("/api/v1/admin/", "/api/v1/teaching/", "/api/v1/promotion-groups", "/api/v1/site")
    ):
        return "administration"
    return "other"


def empty_aggregate() -> dict:
    """Allocate independent counters for one minute/category."""
    return {
        **dict.fromkeys(ADDITIVE, 0),
        "max_us": 0,
        "statuses": Counter(),
        "histogram": Counter(),
    }


def merge_aggregate(target: dict, source: dict) -> None:
    """Merge observations without averaging averages or losing concurrent increments."""
    for key in ADDITIVE:
        target[key] += source[key]
    target["max_us"] = max(target["max_us"], source["max_us"])
    for key in ("statuses", "histogram"):
        target[key].update(source[key])


class ApiMonitor:
    """Keep at most two hours of pending minute/category buckets per application process."""

    def __init__(self) -> None:
        """Allocate request-local-process counters; workers merge through atomic SQL UPSERTs."""
        self.pending: dict[tuple[datetime, str], dict] = {}
        self.dropped = 0
        self.lock = asyncio.Lock()

    def observe(
        self,
        category: str,
        status: int,
        elapsed_us: int,
        *,
        incomplete: bool = False,
        refused: bool = False,
        now: datetime | None = None,
    ) -> None:
        """Record a completed transfer without database work in the request path."""
        bucket = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
        key = (bucket, category)
        if key not in self.pending and len(self.pending) >= 9 * 120:
            oldest = min(self.pending)
            self.dropped += self.pending.pop(oldest)["requests"]
        item = self.pending.setdefault(key, empty_aggregate())
        item["requests"] += 1
        item["duration_us"] += elapsed_us
        item["max_us"] = max(item["max_us"], elapsed_us)
        item["successes"] += int(200 <= status < 300)
        item["redirects"] += int(300 <= status < 400)
        item["client_errors"] += int(400 <= status < 500)
        item["server_errors"] += int(500 <= status < 600)
        item["incomplete"] += int(incomplete)
        item["ics_refused"] += int(refused)
        item["statuses"][str(status)] += 1
        index = next((i for i, bound in enumerate(BOUNDS) if elapsed_us <= bound), len(BOUNDS))
        item["histogram"][str(index)] += 1

    async def flush(self, database: Database) -> None:
        """Persist batches outside HTTP transactions, retry buffers and purge after 31 days."""
        async with self.lock:
            snapshot, self.pending = self.pending, {}
            cutoff = datetime.now(UTC) - timedelta(days=31)
            try:
                async with database.sessions.begin() as session:
                    await session.execute(delete(ApiMetric).where(ApiMetric.bucket < cutoff))
                    rows = [
                        dict(
                            bucket=bucket,
                            category=category,
                            **{
                                key: dict(value) if isinstance(value, Counter) else value
                                for key, value in item.items()
                            },
                        )
                        for (bucket, category), item in snapshot.items()
                        if bucket >= cutoff
                    ]
                    for offset in range(0, len(rows), 200):
                        statement = insert(ApiMetric).values(rows[offset : offset + 200])
                        updates = {
                            key: getattr(ApiMetric, key) + getattr(statement.excluded, key)
                            for key in ADDITIVE
                        }
                        updates["max_us"] = func.greatest(
                            ApiMetric.max_us, statement.excluded.max_us
                        )
                        for key in ("statuses", "histogram"):
                            # All interpolated names are fixed internal SQL identifiers.
                            updates[key] = literal_column(
                                f"(SELECT jsonb_object_agg(k, n) FROM (SELECT k, sum(v::bigint) n "
                                "FROM (SELECT key k, value v FROM "
                                f"jsonb_each_text(api_metrics.{key}) "
                                "UNION ALL SELECT key, value FROM "
                                f"jsonb_each_text(excluded.{key})) a "
                                "GROUP BY k) b)"
                            )
                        await session.execute(
                            statement.on_conflict_do_update(
                                index_elements=[ApiMetric.bucket, ApiMetric.category], set_=updates
                            )
                        )
            except (Exception, asyncio.CancelledError) as error:
                for key, value in snapshot.items():
                    if key in self.pending:
                        merge_aggregate(self.pending[key], value)
                    elif len(self.pending) < 9 * 120:
                        self.pending[key] = value
                    else:
                        self.dropped += value["requests"]
                if isinstance(error, asyncio.CancelledError):
                    raise
                logging.getLogger(__name__).warning(
                    "API monitoring flush unavailable; bounded retry pending"
                )

    async def run(self, database: Database) -> None:
        """Flush at startup and every thirty seconds, including retention during quiet periods."""
        while True:
            await self.flush(database)
            await asyncio.sleep(30)


class ApiMonitoringMiddleware:
    """Measure ASGI transfers, including handled rejections and streaming completion."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application without creating database connections at import time."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Observe final status and elapsed transfer time without reading bodies or credentials."""
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return
        start, status, completed = perf_counter_ns(), 500, False
        elapsed_us: int | None = None

        async def observed_send(message: Message) -> None:
            """Forward messages unchanged and detect the final successfully sent response chunk."""
            nonlocal status, completed, elapsed_us
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
                elapsed_us = max(0, (perf_counter_ns() - start) // 1000)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            monitor = getattr(scope["app"].state, "api_monitor", None)
            if monitor is not None:
                monitor.observe(
                    category_for(scope["path"], scope["method"]),
                    status,
                    elapsed_us
                    if elapsed_us is not None
                    else max(0, (perf_counter_ns() - start) // 1000),
                    incomplete=not completed,
                    refused=completed and status == 200 and scope.get("ics_outcome") == "refused",
                )


def p95(histogram: dict, maximum: int) -> float | None:
    """Estimate the 95th percentile from merged noncumulative buckets in milliseconds."""
    count = sum(histogram.values())
    if not count:
        return None
    threshold, seen = math.ceil(count * 0.95), 0
    for index in range(len(BOUNDS) + 1):
        seen += histogram.get(str(index), 0)
        if seen >= threshold:
            return min(BOUNDS[index] if index < len(BOUNDS) else maximum, maximum) / 1000
    return None


class ApiMonitoringService:
    """Authorize aggregate reads and reduce minute storage in SQL before serialization."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse the request's live authentication and SQL session."""
        self.auth, self.db = auth, auth.db

    async def read(
        self,
        actor: UserContext,
        period: Period,
        category: str = "all",
        interval: datetime | None = None,
    ) -> dict:
        """Return bounded charts, or exact HTTP code counts for one selected chart interval."""
        if category != "all" and category not in CATEGORIES:
            raise AuthError(422, "Catégorie invalide.")
        now = self.auth.clock()
        start, _ = statistics_window(now, period)
        unit = {"day": "minute", "week": "hour", "month": "day"}[period]
        async with self.db.begin():
            await self.auth._actor(actor, permission="statistics.read")
            if interval is not None:
                if interval.tzinfo is None or interval < start or interval > now:
                    raise AuthError(422, "Intervalle invalide.")
                start = interval
                end = (
                    (interval.astimezone(PARIS) + timedelta(days=1)).astimezone(UTC)
                    if unit == "day"
                    else interval + timedelta(**{unit + "s": 1})
                )
                rows = await self.db.execute(
                    text(
                        "SELECT j.key, sum(j.value::bigint) FROM sophikron.api_metrics m "
                        "CROSS JOIN LATERAL jsonb_each_text(m.statuses) j "
                        "WHERE m.bucket >= :start AND m.bucket < :end "
                        "AND (:category = 'all' OR m.category = :category) "
                        "GROUP BY j.key ORDER BY j.key"
                    ),
                    {"start": start, "end": min(end, now), "category": category},
                )
                return {"statuses": {row[0]: row[1] for row in rows}}
            parameters = {
                "start": start,
                "end": now,
                "category": category,
                "unit": unit,
                "zone": "Europe/Paris" if unit == "day" else "UTC",
            }
            rows = (
                (
                    await self.db.execute(
                        text(
                            "SELECT date_trunc(:unit, bucket, :zone) t, sum(requests) requests, "
                            "sum(duration_us) duration_us, max(max_us) max_us, "
                            "sum(successes) successes, "
                            "sum(redirects) redirects, sum(client_errors) client_errors, "
                            "sum(server_errors) server_errors, "
                            "sum(incomplete) incomplete, sum(ics_refused) ics_refused "
                            "FROM sophikron.api_metrics "
                            "WHERE bucket >= :start AND bucket < :end "
                            "AND (:category = 'all' OR category = :category) "
                            "GROUP BY t ORDER BY t"
                        ),
                        parameters,
                    )
                )
                .mappings()
                .all()
            )
            histograms: dict[datetime, dict] = {}
            for bucket, key, count in await self.db.execute(
                text(
                    "SELECT date_trunc(:unit, m.bucket, :zone) t, j.key, "
                    "sum(j.value::bigint) "
                    "FROM sophikron.api_metrics m "
                    "CROSS JOIN LATERAL jsonb_each_text(m.histogram) j "
                    "WHERE m.bucket >= :start AND m.bucket < :end "
                    "AND (:category = 'all' OR category = :category) "
                    "GROUP BY t, j.key"
                ),
                parameters,
            ):
                histograms.setdefault(bucket, {})[key] = int(count)
            category_rows = (
                await self.db.execute(
                    select(
                        ApiMetric.category,
                        func.sum(ApiMetric.requests),
                        func.sum(ApiMetric.duration_us),
                        func.max(ApiMetric.max_us),
                        func.sum(ApiMetric.server_errors),
                    )
                    .where(ApiMetric.bucket >= start, ApiMetric.bucket < now)
                    .group_by(ApiMetric.category)
                )
            ).all()
            category_histograms: dict[str, dict] = {}
            for name, key, count in await self.db.execute(
                text(
                    "SELECT m.category, j.key, sum(j.value::bigint) "
                    "FROM sophikron.api_metrics m "
                    "CROSS JOIN LATERAL jsonb_each_text(m.histogram) j "
                    "WHERE m.bucket >= :start AND m.bucket < :end GROUP BY m.category, j.key"
                ),
                parameters,
            ):
                category_histograms.setdefault(name, {})[key] = int(count)
            points = {row["t"]: dict(row) for row in rows}
            timestamps = monitoring_timestamps(now, period)
            result = []
            total_histogram = Counter()
            total_requests = total_duration = total_errors = maximum = 0
            for timestamp in timestamps:
                item = points.get(timestamp)
                histogram = histograms.get(timestamp, {})
                total_histogram.update(histogram)
                if item:
                    total_requests += int(item["requests"])
                    total_duration += int(item["duration_us"])
                    total_errors += int(item["server_errors"])
                    maximum = max(maximum, int(item["max_us"]))
                result.append(
                    {
                        "timestamp": timestamp,
                        "requests": int(item["requests"]) if item else 0,
                        "mean_ms": float(item["duration_us"] / item["requests"] / 1000)
                        if item
                        else None,
                        "p95_ms": p95(histogram, int(item["max_us"])) if item else None,
                        "max_ms": float(item["max_us"] / 1000) if item else None,
                        **{
                            key: int(item[key]) if item else 0
                            for key in (
                                "successes",
                                "redirects",
                                "client_errors",
                                "server_errors",
                                "incomplete",
                                "ics_refused",
                            )
                        },
                    }
                )
            return {
                "period": period,
                "granularity": unit,
                "category": category,
                "points": result,
                "requests": total_requests,
                "mean_ms": total_duration / total_requests / 1000 if total_requests else None,
                "p95_ms": p95(total_histogram, maximum),
                "server_error_rate": total_errors / total_requests * 100
                if total_requests
                else None,
                "categories": [
                    {
                        "key": row[0],
                        "label": CATEGORIES[row[0]],
                        "requests": row[1],
                        "mean_ms": float(row[2] / row[1] / 1000),
                        "p95_ms": p95(category_histograms.get(row[0], {}), row[3]),
                        "max_ms": float(row[3] / 1000),
                        "server_errors": row[4],
                    }
                    for row in category_rows
                ],
            }
