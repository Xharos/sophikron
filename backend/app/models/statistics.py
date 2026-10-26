"""Anonymous hourly authentication counters; successful identities stay in the audit journal."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, func
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
