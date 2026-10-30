"""Independent promotion partitions, movable groups and pupil assignments."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PromotionPartition(Base):
    """Keep one independently versioned partition of each kind per promotion."""

    __tablename__ = "promotion_partitions"
    __table_args__ = (
        CheckConstraint("kind IN ('halves', 'thirds', 'kholles')", name="kind"),
        CheckConstraint("target_size BETWEEN 2 AND 5", name="target_size"),
    )

    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.promotions.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    revision: Mapped[str] = mapped_column(String(32))
    target_size: Mapped[int] = mapped_column(Integer)


class PromotionGroup(Base):
    """Identify a group by its number within its own partition."""

    __tablename__ = "promotion_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["promotion_id", "kind"],
            ["sophikron.promotion_partitions.promotion_id", "sophikron.promotion_partitions.kind"],
            ondelete="CASCADE",
        ),
        CheckConstraint("number BETWEEN 1 AND 1000", name="number"),
        CheckConstraint("x BETWEEN 0 AND 1000000 AND y BETWEEN 0 AND 1000000", name="position"),
    )

    promotion_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)


class PromotionGroupMember(Base):
    """Enforce one assignment per pupil and partition, tied to promotion membership."""

    __tablename__ = "promotion_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["promotion_id", "kind", "group_number"],
            [
                "sophikron.promotion_groups.promotion_id",
                "sophikron.promotion_groups.kind",
                "sophikron.promotion_groups.number",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "promotion_id"],
            ["sophikron.user_promotions.user_id", "sophikron.user_promotions.promotion_id"],
            ondelete="CASCADE",
        ),
    )

    promotion_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    group_number: Mapped[int] = mapped_column(Integer)


class PromotionCustomGroup(Base):
    """Keep named overlapping audiences independently from numbered partitions."""

    __tablename__ = "promotion_custom_groups"
    __table_args__ = (
        UniqueConstraint("promotion_id", "name_key"),
        UniqueConstraint("id", "promotion_id"),
        CheckConstraint("x BETWEEN 0 AND 1000000 AND y BETWEEN 0 AND 1000000", name="position"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    promotion_id: Mapped[int] = mapped_column(
        ForeignKey("sophikron.promotions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(300))
    revision: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    x: Mapped[int] = mapped_column(Integer, server_default=text("320"))
    y: Mapped[int] = mapped_column(Integer, server_default=text("20"))


class PromotionCustomGroupMember(Base):
    """Allow overlapping groups while enforcing current promotion membership."""

    __tablename__ = "promotion_custom_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "promotion_id"],
            [
                "sophikron.promotion_custom_groups.id",
                "sophikron.promotion_custom_groups.promotion_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "promotion_id"],
            ["sophikron.user_promotions.user_id", "sophikron.user_promotions.promotion_id"],
            ondelete="CASCADE",
        ),
    )
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    promotion_id: Mapped[int] = mapped_column(BigInteger)
