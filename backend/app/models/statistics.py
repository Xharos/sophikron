"""Anonymous hourly authentication counters; successful identities stay in the audit journal."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LoginStatistic(Base):
    """Bound failure storage to one row per hour without storing identifiers or IP addresses."""

    __tablename__ = "login_statistics"
    __table_args__ = (CheckConstraint("failed >= 0 AND limited >= 0", name="counts"),)

    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    failed: Mapped[int] = mapped_column(BigInteger, server_default="0")
    limited: Mapped[int] = mapped_column(BigInteger, server_default="0")
    tracked_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CalendarUsageTotal(Base):
    """Keep durable successful ICS request totals independently of account and token lifecycles."""

    __tablename__ = "calendar_usage_totals"
    __table_args__ = (CheckConstraint("id = 1 AND requests >= 0", name="counts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger, server_default="0")


class ApiMetric(Base):
    """Bound anonymous HTTP measurements to one minute/category row for at most 31 days."""

    __tablename__ = "api_metrics"
    __table_args__ = (
        CheckConstraint(
            "category IN ('auth','timetable_read','timetable_check','timetable_write',"
            "'ics','administration','documents','statistics','other')",
            name="category",
        ),
        CheckConstraint("requests >= 0 AND duration_us >= 0 AND max_us >= 0", name="counts"),
    )
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    category: Mapped[str] = mapped_column(String(24), primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger)
    duration_us: Mapped[int] = mapped_column(BigInteger)
    max_us: Mapped[int] = mapped_column(BigInteger)
    successes: Mapped[int] = mapped_column(BigInteger)
    redirects: Mapped[int] = mapped_column(BigInteger)
    client_errors: Mapped[int] = mapped_column(BigInteger)
    server_errors: Mapped[int] = mapped_column(BigInteger)
    incomplete: Mapped[int] = mapped_column(BigInteger)
    ics_refused: Mapped[int] = mapped_column(BigInteger)
    statuses: Mapped[dict] = mapped_column(JSONB)
    histogram: Mapped[dict] = mapped_column(JSONB)
