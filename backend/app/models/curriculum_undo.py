"""Bounded inverse operations for collaborative programme editing."""

from sqlalchemy import BigInteger, ForeignKey, Identity
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CurriculumUndo(Base):
    """Retain inverse data with the exact revision it can safely undo."""

    __tablename__ = "curriculum_undo"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sophikron.users.id", ondelete="CASCADE"))
    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.curricula.id", ondelete="CASCADE")
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT")
    )
    node_id: Mapped[int] = mapped_column(BigInteger)
    after_version: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB)
