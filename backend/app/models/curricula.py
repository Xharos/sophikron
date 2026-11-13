"""Shared two-year curricula and subject-scoped directed acyclic competency graphs."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Curriculum(Base):
    """Represent one complete pathway and its current multi-subject programme."""

    __tablename__ = "curricula"
    __table_args__ = (CheckConstraint("length(btrim(title)) > 0", name="title"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class CurriculumSubject(Base):
    """Allow only administrator-selected existing subjects in a curriculum."""

    __tablename__ = "curriculum_subjects"
    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.curricula.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"), primary_key=True
    )


class Competency(Base):
    """Store one editable identity regardless of its number of parents."""

    __tablename__ = "competencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["curriculum_id", "subject_id"],
            [
                "sophikron.curriculum_subjects.curriculum_id",
                "sophikron.curriculum_subjects.subject_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("curriculum_id", "subject_id", "id", name="uq_competency_scope"),
        CheckConstraint("length(btrim(name)) > 0", name="name"),
        CheckConstraint("semester BETWEEN 1 AND 4", name="semester"),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),
        CheckConstraint("position >= 0", name="position"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subject_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(300))
    semester: Mapped[int | None] = mapped_column(Integer)
    knowledge: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(7))
    position: Mapped[int] = mapped_column(Integer, server_default="0")


class CompetencyLink(Base):
    """Constrain both ends of an edge to the same curriculum and subject."""

    __tablename__ = "competency_links"
    __table_args__ = (
        *(
            ForeignKeyConstraint(
                ["curriculum_id", "subject_id", endpoint],
                [
                    "sophikron.competencies.curriculum_id",
                    "sophikron.competencies.subject_id",
                    "sophikron.competencies.id",
                ],
                ondelete="CASCADE",
                name=f"fk_competency_links_{endpoint}",
            )
            for endpoint in ("parent_id", "child_id")
        ),
        CheckConstraint("parent_id <> child_id", name="different_nodes"),
    )
    curriculum_id: Mapped[int] = mapped_column(BigInteger)
    subject_id: Mapped[int] = mapped_column(BigInteger)
    parent_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    child_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
