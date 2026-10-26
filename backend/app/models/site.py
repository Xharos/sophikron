"""Administrator-owned subjects, public site settings and annual calendars."""

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subject(Base):
    """Provide one live visual identity shared by every course in a subject."""

    __tablename__ = "subjects"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name"),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(300), unique=True)
    icon: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(7))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class TeacherSubject(Base):
    """Assign teaching staff to a subject; management also requires the teacher role."""

    __tablename__ = "teacher_subjects"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class SiteSettings(Base):
    """Keep public presentation separate from infrastructure credentials."""

    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("holiday_color ~ '^#[0-9A-Fa-f]{6}$'", name="holiday_color"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), server_default="Sophikron")
    home_text: Mapped[str] = mapped_column(Text, server_default="")
    text_color: Mapped[str] = mapped_column(String(7), server_default="#244BC1")
    holiday_color: Mapped[str] = mapped_column(String(7), server_default="#244BC1")
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class Timeline(Base):
    """Describe one independently dated public school-year bar."""

    __tablename__ = "timelines"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="period"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    color: Mapped[str] = mapped_column(String(7))
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class TimelineEvent(Base):
    """Store a shared event once, independently of its display bars."""

    __tablename__ = "timeline_events"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="period"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(7))
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class TimelineEventBar(Base):
    """Associate a shared holiday or event with selected annual timelines."""

    __tablename__ = "timeline_event_bars"

    event_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timeline_events.id", ondelete="CASCADE"), primary_key=True
    )
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.timelines.id", ondelete="CASCADE"), primary_key=True, index=True
    )
