"""Annual live calendars, compact recurring series and opaque personal subscriptions."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
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
    """Keep one annual calendar with a reversible promotion assignment and archive state."""

    __tablename__ = "timetable_calendars"
    __table_args__ = (
        Index(
            "uq_timetable_active_promotion",
            "promotion_id",
            unique=True,
            postgresql_where=text("NOT is_archived AND promotion_id IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(300), unique=True)
    promotion_id: Mapped[int | None] = mapped_column(
        ForeignKey("sophikron.promotions.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[str] = mapped_column(String(32))
    is_paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class TimetableRoom(Base):
    """Provide canonical room identities for cross-agenda conflict warnings."""

    __tablename__ = "timetable_rooms"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    revision: Mapped[str] = mapped_column(String(32))


class TimetableSchoolYear(Base):
    """Identify an immutable academic year and remember whether it was ever used."""

    __tablename__ = "timetable_school_years"
    school_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
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
    """Store the sole annual configuration and the revision of its live recurring events."""

    __tablename__ = "timetable_years"
    __table_args__ = (
        UniqueConstraint("calendar_id"),
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class TimetablePreferences(Base):
    """Version the establishment's annual automatic archive policy."""

    __tablename__ = "timetable_preferences"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auto_archive: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_rollover_year: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[str] = mapped_column(String(32))
