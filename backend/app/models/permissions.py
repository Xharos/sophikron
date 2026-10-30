"""Explicit permission catalogue; administrator roles never imply teacher permissions."""

from sqlalchemy import BigInteger, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Permission(Base):
    """A stable capability code independent of a role name."""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255))


class RolePermission(Base):
    """Grant capabilities explicitly to roles, without implicit role inheritance."""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sophikron.permissions.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
