"""Model inventory REPTIL — mutasi stok (immutable) sebagai satu-satunya sumber saldo."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

REF_TYPES = ("purchase_receipt", "sales_delivery", "adjustment", "opname")


class StockMovement(UUIDPk, TimestampMixin, Base):
    """Mutasi stok. qty positif = masuk, negatif = keluar.

    Tabel ini bersifat append-only: saldo stok TIDAK pernah di-update langsung,
    melainkan dihitung dari penjumlahan mutasi (prinsip audit-friendly).
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_org_item_wh", "organisation_id", "item_id", "warehouse_id"),
        Index("ix_stock_movements_ref", "ref_type", "ref_id"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ref_number: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    item = relationship("Item", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
