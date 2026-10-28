"""Whole-class agendas, annual drafts, normalized series and opaque subscriptions."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimetableCalendar(Base):
    """Keep a reusable agenda independently of its manual promotion assignment."""

    __tablename__ = "timetable_calendars"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    promotion_id: Mapped[int | None] = mapped_column(
        ForeignKey("sophikron.promotions.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[str] = mapped_column(String(32))
    is_paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class TimetableRoom(Base):
    """Provide canonical room identities for cross-agenda conflict warnings."""

    __tablename__ = "timetable_rooms"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    revision: Mapped[str] = mapped_column(String(32))


class TimetableSchoolYear(Base):
    """Share one editable establishment configuration across all annual agendas."""

    __tablename__ = "timetable_school_years"
    school_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    settings: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    revision: Mapped[str] = mapped_column(String(32))


class TeacherAvailability(Base):
    """Store an explicit weekly availability pattern for one teacher and school year."""

    __tablename__ = "teacher_availability"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    school_year: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timetable_school_years.school_year", ondelete="CASCADE"),
        primary_key=True,
    )
    ranges: Mapped[list] = mapped_column(JSONB)
    revision: Mapped[str] = mapped_column(String(32))


class TimetableYear(Base):
    """Keep editable settings separate from the last published annual snapshot."""

    __tablename__ = "timetable_years"
    __table_args__ = (
        UniqueConstraint("calendar_id", "school_year"),
        CheckConstraint("ends_on >= starts_on", name="period"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timetable_calendars.id", ondelete="CASCADE"), index=True
    )
    school_year: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timetable_school_years.school_year")
    )
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    settings: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[str] = mapped_column(String(32))
    published_revision: Mapped[str | None] = mapped_column(String(32))
    published: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimetableSeries(Base):
    """Persist one bounded block series with isolated occurrence exceptions."""

    __tablename__ = "timetable_series"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    year_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timetable_years.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT")
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="RESTRICT")
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("sophikron.timetable_rooms.id", ondelete="RESTRICT")
    )
    data: Mapped[dict] = mapped_column(JSONB)


class TimetableSubscription(Base):
    """Keep exactly one random-token verifier per member, never the original link."""

    __tablename__ = "timetable_subscriptions"
    __table_args__ = (CheckConstraint("octet_length(token_hash) = 32", name="token_length"),)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TimetableTemplateVersion(Base):
    """Keep immutable weekly pattern snapshots and their successive effective dates."""

    __tablename__ = "timetable_template_versions"
    __table_args__ = (
        UniqueConstraint("year_id", "number"),
        CheckConstraint("number > 0", name="number"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    year_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timetable_years.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    effective_on: Mapped[date] = mapped_column(Date)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocks: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
