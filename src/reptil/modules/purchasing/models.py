"""Model purchasing REPTIL: Purchase Order → Penerimaan Barang → Faktur Pembelian."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

PO_STATUSES = ("draft", "received", "invoiced", "cancelled")
INVOICE_STATUSES = ("unpaid", "partial", "paid", "cancelled")


class PurchaseOrder(UUIDPk, TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_purchase_orders_org_number"),
        CheckConstraint(
            "status IN ('draft','received','invoiced','cancelled')", name="status_valid"
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="draft")
    catatan: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    supplier = relationship("Partner", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseOrderLine.line_no"
    )
    invoices: Mapped[list[PurchaseInvoice]] = relationship(back_populates="order", lazy="selectin")


class PurchaseOrderLine(UUIDPk, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positif"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    harga: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    catatan: Mapped[str | None] = mapped_column(Text)

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    item = relationship("Item", lazy="joined")


class PurchaseInvoice(UUIDPk, TimestampMixin, Base):
    __tablename__ = "purchase_invoices"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_purchase_invoices_org_number"),
        CheckConstraint("status IN ('unpaid','partial','paid','cancelled')", name="status_valid"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_ref: Mapped[str | None] = mapped_column(String(60))  # no. faktur dari supplier
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    jatuh_tempo: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="unpaid")
    catatan: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    supplier = relationship("Partner", lazy="joined")
    order: Mapped[PurchaseOrder | None] = relationship(back_populates="invoices", lazy="joined")
    lines: Mapped[list[PurchaseInvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseInvoiceLine.line_no"
    )


class PurchaseInvoiceLine(UUIDPk, Base):
    __tablename__ = "purchase_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    deskripsi: Mapped[str | None] = mapped_column(String(200))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    harga: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")
    item = relationship("Item", lazy="joined")
