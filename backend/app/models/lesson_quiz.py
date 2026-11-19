"""Immutable course quiz versions and the recorded first student passage."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LessonQuizVersion(Base):
    """Freeze shared question content independently of the mutable quiz bank."""

    __tablename__ = "lesson_quiz_versions"
    __table_args__ = (
        UniqueConstraint("element_id", "id"),
        CheckConstraint("jsonb_array_length(refs) BETWEEN 1 AND 50", name="size"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    element_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.lesson_elements.id", ondelete="CASCADE"), index=True
    )
    refs: Mapped[list[dict]] = mapped_column(JSONB)
    cards: Mapped[list[dict]] = mapped_column(JSONB, deferred=True)


class LessonQuizPassage(Base):
    """Keep one passage per block and student, including only correction counters."""

    __tablename__ = "lesson_quiz_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["element_id", "version_id"],
            ["sophikron.lesson_quiz_versions.element_id", "sophikron.lesson_quiz_versions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "position >= 0 AND position <= jsonb_array_length(card_order)", name="position"
        ),
        CheckConstraint(
            "jsonb_array_length(card_order) = jsonb_array_length(trials)", name="trial_count"
        ),
    )

    element_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    version_id: Mapped[int] = mapped_column(BigInteger)
    card_order: Mapped[list[int]] = mapped_column(JSONB)
    trials: Mapped[list[int]] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
