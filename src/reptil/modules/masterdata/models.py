"""Model master data REPTIL: Partner, Item, Warehouse."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

PARTNER_TYPES = ("customer", "supplier", "both")
ITEM_TYPES = ("produk", "jasa")


class Partner(UUIDPk, TimestampMixin, Base):
    """Pelanggan dan/atau pemasok — satu entitas, tipe menentukan perannya."""

    __tablename__ = "partners"
    __table_args__ = (
        UniqueConstraint("organisation_id", "kode", name="uq_partners_org_kode"),
        CheckConstraint("tipe IN ('customer','supplier','both')", name="tipe"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kode: Mapped[str] = mapped_column(String(30), nullable=False)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    tipe: Mapped[str] = mapped_column(String(10), nullable=False, default="customer")
    npwp: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255))
    telepon: Mapped[str | None] = mapped_column(String(40))
    alamat: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Item(UUIDPk, TimestampMixin, Base):
    """Barang/jasa. Berat & volume dipakai modul logistik untuk kalkulasi muatan."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("organisation_id", "sku", name="uq_items_org_sku"),
        CheckConstraint("tipe IN ('produk','jasa')", name="tipe"),
        CheckConstraint("berat_kg >= 0", name="berat_negatif"),
        CheckConstraint("volume_m3 >= 0", name="volume_negatif"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    deskripsi: Mapped[str | None] = mapped_column(Text)
    tipe: Mapped[str] = mapped_column(String(10), nullable=False, default="produk")
    satuan: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    berat_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    # Harga acuan — dipakai sebagai nilai default saat membuat dokumen pembelian/penjualan
    harga_beli: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    harga_jual: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    stok_minimum: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Warehouse(UUIDPk, TimestampMixin, Base):
    """Gudang tempat stok disimpan — boleh banyak per organisasi."""

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("organisation_id", "kode", name="uq_warehouses_org_kode"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kode: Mapped[str] = mapped_column(String(30), nullable=False)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    alamat: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
