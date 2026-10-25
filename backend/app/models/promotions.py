"""Promotion catalogue and role-independent account memberships."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Promotion(Base):
    """A reversible archive state preserves the promotion and its memberships."""

    __tablename__ = "promotions"
    __table_args__ = (
        UniqueConstraint("year", "identifier"),
        CheckConstraint("year BETWEEN 1 AND 9999", name="year"),
        CheckConstraint(
            "identifier = btrim(identifier) AND length(identifier) > 0", name="identifier"
        ),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    identifier: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(7))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserPromotion(Base):
    """Associate any permanent account with any number of promotions."""

    __tablename__ = "user_promotions"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    promotion_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sophikron.promotions.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
