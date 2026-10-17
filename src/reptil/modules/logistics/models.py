"""Model logistik REPTIL: armada, ekspedisi, pengiriman, rute, dan pelacakan.

Alur (docs/DESAIN.md §4.7): Sales Order terkirim → Shipment (parsing berat/volume
dari item) → armada/ekspedisi → update status → ShipmentStatusHistory (tracking).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

# created → picked_up → in_transit → delivered/failed
SHIPMENT_STATUSES = ("created", "picked_up", "in_transit", "delivered", "failed")
VEHICLE_STATUSES = ("tersedia", "dalam_tugas", "perbaikan")
ROUTE_STATUSES = ("draft", "berjalan", "selesai")
STOP_STATUSES = ("pending", "tiba", "batal")


class Vehicle(UUIDPk, TimestampMixin, Base):
    """Armada/kendaraan. Kapasitas dipakai untuk memeriksa muatan pengiriman."""

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("organisation_id", "kode", name="uq_vehicles_org_kode"),
        CheckConstraint("status IN ('tersedia','dalam_tugas','perbaikan')", name="status_valid"),
        CheckConstraint("kapasitas_kg >= 0", name="kapasitas_kg_negatif"),
        CheckConstraint("kapasitas_m3 >= 0", name="kapasitas_m3_negatif"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kode: Mapped[str] = mapped_column(String(30), nullable=False)
    nama: Mapped[str] = mapped_column(String(150), nullable=False)
    tipe: Mapped[str] = mapped_column(String(30), nullable=False, default="truk")
    plat: Mapped[str | None] = mapped_column(String(20))
    kapasitas_kg: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    kapasitas_m3: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    pengemudi: Mapped[str | None] = mapped_column(String(150))
    telepon_pengemudi: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="tersedia")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Carrier(UUIDPk, TimestampMixin, Base):
    """Ekspedisi/kurir pihak ketiga (JNE, J&T, SiCepat, …)."""

    __tablename__ = "carriers"
    __table_args__ = (UniqueConstraint("organisation_id", "kode", name="uq_carriers_org_kode"),)

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kode: Mapped[str] = mapped_column(String(30), nullable=False)
    nama: Mapped[str] = mapped_column(String(150), nullable=False)
    telepon: Mapped[str | None] = mapped_column(String(40))
    # Template URL pelacakan, mis. https://track.example.com/{resi}
    tracking_url: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Shipment(UUIDPk, TimestampMixin, Base):
    """Surat jalan/pengiriman. Satu SO bisa dipecah jadi beberapa shipment."""

    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_shipments_org_number"),
        CheckConstraint(
            "status IN ('created','picked_up','in_transit','delivered','failed')",
            name="status_valid",
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carriers.id", ondelete="SET NULL")
    )
    resi: Mapped[str | None] = mapped_column(String(60))  # nomor resi dari ekspedisi
    alamat_kirim: Mapped[str | None] = mapped_column(Text)
    penerima: Mapped[str | None] = mapped_column(String(150))
    telepon_penerima: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="created")
    total_berat_kg: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    total_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    catatan: Mapped[str | None] = mapped_column(Text)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    customer = relationship("Partner", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
    vehicle = relationship("Vehicle", lazy="joined")
    carrier = relationship("Carrier", lazy="joined")
    order = relationship("SalesOrder", lazy="joined")
    lines: Mapped[list[ShipmentLine]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ShipmentLine.line_no",
    )
    history: Mapped[list[ShipmentStatusHistory]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ShipmentStatusHistory.created_at",
    )


class ShipmentLine(UUIDPk, Base):
    """Rincian barang terkirim — berat/volume dihitung dari master item x qty."""

    __tablename__ = "shipment_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positif"),)

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    berat_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    volume_m3: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))

    shipment: Mapped[Shipment] = relationship(back_populates="lines")
    item = relationship("Item", lazy="joined")


class ShipmentStatusHistory(UUIDPk, TimestampMixin, Base):
    """Riwayat status pengiriman (tracking). Append-only."""

    __tablename__ = "shipment_status_history"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(15), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    shipment: Mapped[Shipment] = relationship(back_populates="history")


class Route(UUIDPk, TimestampMixin, Base):
    """Rute pengiriman dengan beberapa titik berhenti (multi-stop)."""

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_routes_org_number"),
        CheckConstraint("status IN ('draft','berjalan','selesai')", name="status_valid"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    nama: Mapped[str] = mapped_column(String(150), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="draft")
    catatan: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    vehicle = relationship("Vehicle", lazy="joined")
    stops: Mapped[list[RouteStop]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RouteStop.urutan",
    )


class RouteStop(UUIDPk, TimestampMixin, Base):
    """Titik berhenti pada rute. `jarak_km` = perhitungan beban dasar."""

    __tablename__ = "route_stops"
    __table_args__ = (
        CheckConstraint("status IN ('pending','tiba','batal')", name="status_valid"),
        CheckConstraint("jarak_km >= 0", name="jarak_negatif"),
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    urutan: Mapped[int] = mapped_column(nullable=False)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL")
    )
    alamat: Mapped[str] = mapped_column(Text, nullable=False)
    jarak_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending")
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catatan: Mapped[str | None] = mapped_column(Text)

    route: Mapped[Route] = relationship(back_populates="stops")
    shipment = relationship("Shipment", lazy="joined")
