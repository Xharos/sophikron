"""Course pages, ordered extensible elements and revocable account/promotion grants."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Lesson(Base):
    """Keep the original author independently of their current account permissions."""

    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title"),
        CheckConstraint("version >= 0", name="version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    creator_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    title_key: Mapped[str] = mapped_column(String(480), unique=True)
    description: Mapped[str] = mapped_column(String(2000))
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"), index=True
    )
    responsible_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonElement(Base):
    """Store stable element IDs so future documents can attach to the same content tree."""

    __tablename__ = "lesson_elements"
    __table_args__ = (
        UniqueConstraint("lesson_id", "id"),
        ForeignKeyConstraint(
            ["lesson_id", "parent_id"],
            ["sophikron.lesson_elements.lesson_id", "sophikron.lesson_elements.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "kind IN ('section', 'subsection', 'text', 'youtube', 'file', 'table')", name="kind"
        ),
        CheckConstraint("audience IN ('students', 'staff')", name="audience"),
        CheckConstraint("kind = 'section' OR audience = 'students'", name="section_audience"),
        CheckConstraint(
            "kind IN ('file', 'youtube') OR "
            "(schedule_mode = 'inherit' AND starts_on IS NULL AND ends_on IS NULL)",
            name="resource_dates",
        ),
        CheckConstraint(
            "table_rows BETWEEN 1 AND 20 AND jsonb_array_length(table_columns) BETWEEN 1 AND 6",
            name="table_dimensions",
        ),
        CheckConstraint(
            "(row_index IS NULL AND column_index IS NULL) OR "
            "(row_index IS NOT NULL AND column_index IS NOT NULL "
            "AND row_index BETWEEN 0 AND 19 AND column_index BETWEEN 0 AND 5)",
            name="cell_coordinates",
        ),
        UniqueConstraint("parent_id", "row_index", "column_index"),
        CheckConstraint("(kind = 'section') = (parent_id IS NULL)", name="root_section"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint(
            "(schedule_mode = 'inherit' AND starts_on IS NULL AND ends_on IS NULL) OR "
            "(schedule_mode = 'from' AND starts_on IS NOT NULL AND ends_on IS NULL) OR "
            "(schedule_mode = 'range' AND starts_on IS NOT NULL AND ends_on IS NOT NULL "
            "AND ends_on >= starts_on)",
            name="schedule",
        ),
        CheckConstraint(
            "(kind IN ('section', 'subsection', 'table', 'file') "
            "AND length(btrim(title)) > 0 AND body = '') OR "
            "(kind IN ('text', 'youtube') AND length(btrim(body)) > 0)",
            name="content",
        ),
        CheckConstraint("length(body) <= 3000", name="body_length"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.lessons.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), server_default="")
    body: Mapped[str] = mapped_column(Text, server_default="")
    schedule_mode: Mapped[str] = mapped_column(String(16), server_default="inherit")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    audience: Mapped[str] = mapped_column(String(16), server_default="students")
    table_rows: Mapped[int] = mapped_column(Integer, server_default="1")
    table_columns: Mapped[list[str]] = mapped_column(JSONB, server_default='["Colonne 1"]')
    row_index: Mapped[int | None] = mapped_column(Integer)
    column_index: Mapped[int | None] = mapped_column(Integer)


class LessonFile(Base):
    """Keep immutable file facts separate from author-selected display titles and access rules."""

    __tablename__ = "lesson_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lesson_id", "element_id"],
            ["sophikron.lesson_elements.lesson_id", "sophikron.lesson_elements.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 52428800", name="size"),
        CheckConstraint(
            "storage_key ~ '^[0-9a-f]{32}$' AND sha256 ~ '^[0-9a-f]{64}$'", name="digest_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lesson_id: Mapped[int] = mapped_column(BigInteger, index=True)
    element_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="RESTRICT"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    original_name: Mapped[str] = mapped_column(String(200))
    extension: Mapped[str] = mapped_column(String(8))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonUpload(Base):
    """Reserve quota and a single-use upload independently of long-running body transfers."""

    __tablename__ = "lesson_uploads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.lessons.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), index=True
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LessonFileDeletion(Base):
    """Retain deletion intent even after SQL cascades remove a whole course."""

    __tablename__ = "lesson_file_deletions"
    storage_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonCollaborator(Base):
    """Membership alone never authorizes editing without a current teacher capability."""

    __tablename__ = "lesson_collaborators"

    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.lessons.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class LessonPromotion(Base):
    """Grant a promotion an explicit inclusive school-year access period."""

    __tablename__ = "lesson_promotions"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="period"),)

    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.lessons.id", ondelete="CASCADE"), primary_key=True
    )
    promotion_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.promotions.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
