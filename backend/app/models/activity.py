"""Append-only structured application events with extensible resource references."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivityEvent(Base):
    """Record successful facts; resource references are validated by their emitting service."""

    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint("event_type ~ '^[a-z][a-z0-9_.]{0,95}$'", name="event_type"),
        CheckConstraint("schema_version > 0", name="schema_version"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="data_object"),
        CheckConstraint("octet_length(data::text) <= 4096", name="data_size"),
        CheckConstraint(
            "actor_role IN ('admin', 'teacher', 'kholleur', 'user')", name="actor_role"
        ),
        CheckConstraint(
            "subject_role IN ('admin', 'teacher', 'kholleur', 'user')", name="subject_role"
        ),
        CheckConstraint("actor_user_id IS NOT NULL OR actor_role IS NULL", name="actor_snapshot"),
        CheckConstraint(
            "subject_user_id IS NOT NULL OR subject_role IS NULL", name="subject_snapshot"
        ),
        CheckConstraint(
            "promotion_snapshot IS NULL OR (resource_type = 'promotion' AND "
            "jsonb_typeof(promotion_snapshot) = 'object' AND "
            "octet_length(promotion_snapshot::text) <= 1024)",
            name="promotion_snapshot",
        ),
        CheckConstraint(
            "(resource_type IS NULL AND resource_id IS NULL) OR "
            "(resource_type IS NOT NULL AND resource_id IS NOT NULL AND resource_id > 0)",
            name="resource",
        ),
        Index("ix_activity_events_time_id", "occurred_at", "id"),
        Index("ix_activity_events_type_time_id", "event_type", "occurred_at", "id"),
        Index("ix_activity_events_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_activity_events_subject_time", "subject_user_id", "occurred_at"),
        Index("ix_activity_events_resource", "resource_type", "resource_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="RESTRICT")
    )
    subject_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="RESTRICT")
    )
    actor_role: Mapped[str | None] = mapped_column(String(16))
    subject_role: Mapped[str | None] = mapped_column(String(16))
    promotion_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    data: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
