"""Durable installation-wide GitHub release check cache."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReleaseCheck(Base):
    """Retain the latest successful release independently of failed daily checks."""

    __tablename__ = "release_check"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str | None] = mapped_column(String(100))
    release_url: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(String(200))
