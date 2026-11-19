"""Private question bank and its optional curriculum associations."""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuizQuestion(Base):
    """Store a standalone question and its type-specific correction rule."""

    __tablename__ = "quiz_questions"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title"),
        CheckConstraint("length(btrim(prompt)) > 0", name="prompt"),
        CheckConstraint("kind IN ('choice', 'number', 'text')", name="kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    statement: Mapped[str] = mapped_column(String(4000), server_default="")
    prompt: Mapped[str] = mapped_column(String(4000))
    kind: Mapped[str] = mapped_column(String(10))
    rule: Mapped[dict] = mapped_column(JSONB)
    image: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str] = mapped_column(String(300), server_default="")
    archived: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class QuizQuestionCompetency(Base):
    """Remove only the association when a competency is deleted."""

    __tablename__ = "quiz_question_competencies"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.quiz_questions.id", ondelete="CASCADE"), primary_key=True
    )
    competency_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.competencies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
