"""Model sales REPTIL: Sales Order → Pengiriman → Faktur Penjualan."""

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

SO_STATUSES = ("draft", "delivered", "invoiced", "cancelled")
INVOICE_STATUSES = ("unpaid", "paid", "cancelled")


class SalesOrder(UUIDPk, TimestampMixin, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_sales_orders_org_number"),
        CheckConstraint(
            "status IN ('draft','delivered','invoiced','cancelled')", name="status_valid"
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="draft")
    catatan: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    customer = relationship("Partner", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
    lines: Mapped[list[SalesOrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="SalesOrderLine.line_no"
    )
    invoices: Mapped[list[SalesInvoice]] = relationship(back_populates="order", lazy="selectin")


class SalesOrderLine(UUIDPk, Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positif"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    harga: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    order: Mapped[SalesOrder] = relationship(back_populates="lines")
    item = relationship("Item", lazy="joined")


class SalesInvoice(UUIDPk, TimestampMixin, Base):
    __tablename__ = "sales_invoices"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_sales_invoices_org_number"),
        CheckConstraint("status IN ('unpaid','partial','paid','cancelled')", name="status_valid"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    jatuh_tempo: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="unpaid")
    catatan: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    customer = relationship("Partner", lazy="joined")
    order: Mapped[SalesOrder | None] = relationship(back_populates="invoices", lazy="joined")
    lines: Mapped[list[SalesInvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin", order_by="SalesInvoiceLine.line_no"
    )


class SalesInvoiceLine(UUIDPk, Base):
    __tablename__ = "sales_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    deskripsi: Mapped[str | None] = mapped_column(String(200))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    harga: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")
    item = relationship("Item", lazy="joined")
