"""Model identitas REPTIL: Organisation, User, Role (RBAC), relasi user_roles."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

# Asosiasi banyak-ke-banyak User ↔ Role
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Organisation(UUIDPk, TimestampMixin, Base):
    """Perusahaan/cabang — semua data bisnis terikat ke satu organisasi."""

    __tablename__ = "organisations"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    users: Mapped[list[User]] = relationship(back_populates="organisation")


class User(UUIDPk, TimestampMixin, Base):
    """Pengguna login.

    Email unik **global** — satu email satu akun. Organisasi mengikuti akun,
    jadi pengguna otomatis hanya melihat data perusahaannya sendiri.
    """

    __tablename__ = "users"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organisation: Mapped[Organisation] = relationship(back_populates="users")
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )


class Role(UUIDPk, TimestampMixin, Base):
    """Peran + daftar izin (permission codes) dalam satu organisasi."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_roles_org_name"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Daftar kode izin, mis. ["inventory.read", "sales.approve"]
    permissions: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
