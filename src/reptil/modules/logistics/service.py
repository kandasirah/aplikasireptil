"""Service logistik REPTIL — armada, ekspedisi, pengiriman, rute & tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from reptil.core.documents import next_number_safe
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.events import ShipmentStatusChanged, event_bus
from reptil.core.parsing import to_date, to_decimal
from reptil.modules.logistics.models import (
    ROUTE_STATUSES,
    SHIPMENT_STATUSES,
    STOP_STATUSES,
    VEHICLE_STATUSES,
    Carrier,
    Route,
    RouteStop,
    Shipment,
    ShipmentLine,
    ShipmentStatusHistory,
    Vehicle,
)
from reptil.modules.masterdata.service import get_item, get_warehouse

# Status yang menandakan barang sudah mulai bergerak / sudah tiba.
_STATUS_BERANGKAT = ("picked_up", "in_transit")
_STATUS_TIBA = ("delivered",)


# ------------------------------------------------------------------- armada
def list_vehicles(
    db: Session, organisation_id: uuid.UUID, q: str = "", status: str = ""
) -> list[Vehicle]:
    stmt = select(Vehicle).where(Vehicle.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Vehicle.nama.ilike(like) | Vehicle.kode.ilike(like) | Vehicle.plat.ilike(like)
        )
    if status in VEHICLE_STATUSES:
        stmt = stmt.where(Vehicle.status == status)
    return list(db.execute(stmt.order_by(Vehicle.nama)).scalars().all())


def get_vehicle(db: Session, organisation_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    obj = db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Armada tidak ditemukan.")
    return obj


def save_vehicle(
    db: Session, organisation_id: uuid.UUID, data: dict, vehicle_id: uuid.UUID | None = None
) -> Vehicle:
    kode = (data.get("kode") or "").strip()
    nama = (data.get("nama") or "").strip()
    status = data.get("status") or "tersedia"
    if not kode:
        raise BusinessRuleError("Kode armada wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama armada wajib diisi.")
    if status not in VEHICLE_STATUSES:
        raise BusinessRuleError("Status armada tidak valid.")

    obj = (
        get_vehicle(db, organisation_id, vehicle_id)
        if vehicle_id
        else Vehicle(organisation_id=organisation_id)
    )
    obj.kode, obj.nama, obj.status = kode, nama, status
    obj.tipe = (data.get("tipe") or "truk").strip()
    obj.plat = (data.get("plat") or "").strip() or None
    obj.kapasitas_kg = to_decimal(data.get("kapasitas_kg"), "Kapasitas (kg)", default=Decimal("0"))
    obj.kapasitas_m3 = to_decimal(data.get("kapasitas_m3"), "Kapasitas (m³)", default=Decimal("0"))
    if obj.kapasitas_kg < 0 or obj.kapasitas_m3 < 0:
        raise BusinessRuleError("Kapasitas tidak boleh negatif.")
    obj.pengemudi = (data.get("pengemudi") or "").strip() or None
    obj.telepon_pengemudi = (data.get("telepon_pengemudi") or "").strip() or None
    obj.is_active = bool(data.get("is_active", True))

    db.add(obj)
    _commit(db, f"Kode armada '{kode}' sudah dipakai.")
    return obj


# ---------------------------------------------------------------- ekspedisi
def list_carriers(db: Session, organisation_id: uuid.UUID, q: str = "") -> list[Carrier]:
    stmt = select(Carrier).where(Carrier.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Carrier.nama.ilike(like) | Carrier.kode.ilike(like))
    return list(db.execute(stmt.order_by(Carrier.nama)).scalars().all())


def get_carrier(db: Session, organisation_id: uuid.UUID, carrier_id: uuid.UUID) -> Carrier:
    obj = db.execute(
        select(Carrier).where(Carrier.id == carrier_id, Carrier.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Ekspedisi tidak ditemukan.")
    return obj


def save_carrier(
    db: Session, organisation_id: uuid.UUID, data: dict, carrier_id: uuid.UUID | None = None
) -> Carrier:
    kode = (data.get("kode") or "").strip()
    nama = (data.get("nama") or "").strip()
    if not kode:
        raise BusinessRuleError("Kode ekspedisi wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama ekspedisi wajib diisi.")

    obj = (
        get_carrier(db, organisation_id, carrier_id)
        if carrier_id
        else Carrier(organisation_id=organisation_id)
    )
    obj.kode, obj.nama = kode, nama
    obj.telepon = (data.get("telepon") or "").strip() or None
    obj.tracking_url = (data.get("tracking_url") or "").strip() or None
    obj.is_active = bool(data.get("is_active", True))

    db.add(obj)
    _commit(db, f"Kode ekspedisi '{kode}' sudah dipakai.")
    return obj


# --------------------------------------------------------------- pengiriman
def list_shipments(
    db: Session, organisation_id: uuid.UUID, q: str = "", status: str = ""
) -> list[Shipment]:
    stmt = (
        select(Shipment)
        .options(selectinload(Shipment.lines))
        .where(Shipment.organisation_id == organisation_id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Shipment.number.ilike(like) | Shipment.resi.ilike(like))
    if status in SHIPMENT_STATUSES:
        stmt = stmt.where(Shipment.status == status)
    return list(db.execute(stmt.order_by(Shipment.created_at.desc())).scalars().all())


def get_shipment(db: Session, organisation_id: uuid.UUID, shipment_id: uuid.UUID) -> Shipment:
    obj = db.execute(
        select(Shipment)
        .options(selectinload(Shipment.lines), selectinload(Shipment.history))
        .where(Shipment.id == shipment_id, Shipment.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Pengiriman tidak ditemukan.")
    return obj


def create_shipment(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    customer_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    lines: list[dict],
    vehicle_id: uuid.UUID | None = None,
    carrier_id: uuid.UUID | None = None,
    alamat_kirim: str | None = None,
    penerima: str | None = None,
    telepon_penerima: str | None = None,
    resi: str | None = None,
    catatan: str | None = None,
    sales_order_id: uuid.UUID | None = None,
) -> Shipment:
    """Buat pengiriman; berat/volume tiap baris dihitung dari master item x qty."""
    get_warehouse(db, organisation_id, warehouse_id)  # validasi kepemilikan gudang

    if not lines:
        raise BusinessRuleError("Pengiriman harus punya minimal satu baris item.")

    shipment = Shipment(
        organisation_id=organisation_id,
        number=next_number_safe(db, Shipment, organisation_id, "SJ"),
        sales_order_id=sales_order_id,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        vehicle_id=vehicle_id,
        carrier_id=carrier_id,
        resi=(resi or "").strip() or None,
        alamat_kirim=(alamat_kirim or "").strip() or None,
        penerima=(penerima or "").strip() or None,
        telepon_penerima=(telepon_penerima or "").strip() or None,
        catatan=(catatan or "").strip() or None,
        status="created",
        created_by=user_id,
    )

    total_berat = Decimal("0")
    total_volume = Decimal("0")
    for i, raw in enumerate(lines, start=1):
        qty = to_decimal(raw.get("qty"), "Qty")
        if qty <= 0:
            raise BusinessRuleError("Qty setiap baris harus lebih besar dari nol.")
        try:
            item_id = uuid.UUID(str(raw["item_id"]))
        except (KeyError, ValueError) as exc:
            raise BusinessRuleError("Baris pengiriman tidak punya item yang valid.") from exc
        item = get_item(db, organisation_id, item_id)
        berat = (item.berat_kg or Decimal("0")) * qty
        volume = (item.volume_m3 or Decimal("0")) * qty
        total_berat += berat
        total_volume += volume
        shipment.lines.append(
            ShipmentLine(line_no=i, item_id=item.id, qty=qty, berat_kg=berat, volume_m3=volume)
        )

    shipment.total_berat_kg = total_berat
    shipment.total_volume_m3 = total_volume
    _periksa_kapasitas(db, organisation_id, vehicle_id, total_berat, total_volume)

    shipment.history.append(
        ShipmentStatusHistory(status="created", note="Pengiriman dibuat", created_by=user_id)
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def create_shipment_from_order(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    order_id: uuid.UUID,
    vehicle_id: uuid.UUID | None = None,
    carrier_id: uuid.UUID | None = None,
    alamat_kirim: str | None = None,
    penerima: str | None = None,
    telepon_penerima: str | None = None,
    resi: str | None = None,
    catatan: str | None = None,
) -> Shipment:
    """Buat pengiriman dari Sales Order yang sudah dikirim."""
    from reptil.modules.sales.service import get_order

    order = get_order(db, organisation_id, order_id)
    if order.status not in ("delivered", "invoiced"):
        raise BusinessRuleError(
            f"SO {order.number} berstatus '{order.status}' — "
            "kirim barang dulu sebelum membuat pengiriman."
        )
    sudah = db.execute(
        select(Shipment.id).where(Shipment.sales_order_id == order.id, Shipment.status != "failed")
    ).first()
    if sudah:
        raise BusinessRuleError(f"SO {order.number} sudah punya pengiriman aktif.")

    lines = [{"item_id": str(line.item_id), "qty": line.qty} for line in order.lines]
    return create_shipment(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        customer_id=order.customer_id,
        warehouse_id=order.warehouse_id,
        lines=lines,
        vehicle_id=vehicle_id,
        carrier_id=carrier_id,
        alamat_kirim=alamat_kirim or order.customer.alamat,
        penerima=penerima or order.customer.nama,
        telepon_penerima=telepon_penerima or order.customer.telepon,
        resi=resi,
        catatan=catatan,
        sales_order_id=order.id,
    )


def orders_siap_kirim(db: Session, organisation_id: uuid.UUID) -> list:
    """SO berstatus terkirim yang belum punya pengiriman aktif (untuk form shipment)."""
    from reptil.modules.sales.service import list_orders

    sudah = set(
        db.execute(
            select(Shipment.sales_order_id).where(
                Shipment.organisation_id == organisation_id,
                Shipment.sales_order_id.is_not(None),
                Shipment.status != "failed",
            )
        )
        .scalars()
        .all()
    )
    return [o for o in list_orders(db, organisation_id, status="delivered") if o.id not in sudah]


def update_status(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    shipment_id: uuid.UUID,
    status: str,
    note: str | None = None,
) -> Shipment:
    """Ubah status pengiriman, catat riwayat, dan publikasikan event."""
    if status not in SHIPMENT_STATUSES:
        raise BusinessRuleError("Status pengiriman tidak valid.")
    shipment = get_shipment(db, organisation_id, shipment_id)
    if shipment.status == status:
        raise BusinessRuleError(f"Pengiriman {shipment.number} sudah berstatus '{status}'.")

    shipment.status = status
    now = datetime.now(UTC)
    if status in _STATUS_BERANGKAT and shipment.shipped_at is None:
        shipment.shipped_at = now
    if status in _STATUS_TIBA and shipment.delivered_at is None:
        shipment.delivered_at = now
    shipment.history.append(
        ShipmentStatusHistory(status=status, note=(note or "").strip() or None, created_by=user_id)
    )
    _set_vehicle_status(db, shipment, status)

    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    event_bus.publish(
        ShipmentStatusChanged(
            shipment_id=str(shipment.id),
            status=status,
            note=(note or "").strip() or None,
        )
    )
    return shipment


def shipment_summary(db: Session, organisation_id: uuid.UUID) -> dict:
    """Ringkasan untuk dashboard logistik."""

    def count_status(status: str) -> int:
        return db.execute(
            select(func.count())
            .select_from(Shipment)
            .where(Shipment.organisation_id == organisation_id, Shipment.status == status)
        ).scalar_one()

    entah_kirim = db.execute(
        select(func.count())
        .select_from(Shipment)
        .where(
            Shipment.organisation_id == organisation_id,
            Shipment.status.in_(("picked_up", "in_transit")),
        )
    ).scalar_one()
    return {
        "dibuat": count_status("created"),
        "dalam_perjalanan": entah_kirim,
        "terkirim": count_status("delivered"),
        "gagal": count_status("failed"),
    }


# -------------------------------------------------------------------- rute
def list_routes(
    db: Session, organisation_id: uuid.UUID, q: str = "", status: str = ""
) -> list[Route]:
    stmt = (
        select(Route)
        .options(selectinload(Route.stops))
        .where(Route.organisation_id == organisation_id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Route.nama.ilike(like) | Route.number.ilike(like))
    if status in ROUTE_STATUSES:
        stmt = stmt.where(Route.status == status)
    return list(
        db.execute(stmt.order_by(Route.tanggal.desc(), Route.created_at.desc())).scalars().all()
    )


def get_route(db: Session, organisation_id: uuid.UUID, route_id: uuid.UUID) -> Route:
    obj = db.execute(
        select(Route)
        .options(selectinload(Route.stops))
        .where(Route.id == route_id, Route.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Rute tidak ditemukan.")
    return obj


def save_route(
    db: Session,
    organisation_id: uuid.UUID,
    data: dict,
    route_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Route:
    nama = (data.get("nama") or "").strip()
    if not nama:
        raise BusinessRuleError("Nama rute wajib diisi.")

    obj = (
        get_route(db, organisation_id, route_id)
        if route_id
        else Route(
            organisation_id=organisation_id,
            number=next_number_safe(db, Route, organisation_id, "RT"),
            created_by=user_id,
        )
    )
    obj.nama = nama
    obj.tanggal = to_date(data.get("tanggal"), "Tanggal rute", default=date.today())
    obj.vehicle_id = uuid.UUID(str(data["vehicle_id"])) if data.get("vehicle_id") else None
    status = data.get("status") or "draft"
    if status not in ROUTE_STATUSES:
        raise BusinessRuleError("Status rute tidak valid.")
    obj.status = status
    obj.catatan = (data.get("catatan") or "").strip() or None

    db.add(obj)
    _commit(db, f"Rute '{nama}' bentrok dengan data lain.")
    return obj


def add_stop(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    route_id: uuid.UUID,
    alamat: str,
    shipment_id: uuid.UUID | None = None,
    jarak_km: object = None,
    catatan: str | None = None,
) -> RouteStop:
    route = get_route(db, organisation_id, route_id)
    if not (alamat or "").strip():
        raise BusinessRuleError("Alamat titik berhenti wajib diisi.")
    urutan = max((s.urutan for s in route.stops), default=0) + 1
    stop = RouteStop(
        route_id=route.id,
        urutan=urutan,
        shipment_id=shipment_id,
        alamat=alamat.strip(),
        jarak_km=to_decimal(jarak_km, "Jarak (km)", default=Decimal("0")),
        catatan=(catatan or "").strip() or None,
        status="pending",
    )
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop


def update_stop_status(
    db: Session, *, organisation_id: uuid.UUID, stop_id: uuid.UUID, status: str
) -> RouteStop:
    if status not in STOP_STATUSES:
        raise BusinessRuleError("Status titik tidak valid.")
    stop = db.execute(
        select(RouteStop)
        .join(Route, Route.id == RouteStop.route_id)
        .where(RouteStop.id == stop_id, Route.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if stop is None:
        raise NotFoundError("Titik berhenti tidak ditemukan.")
    stop.status = status
    stop.arrived_at = datetime.now(UTC) if status == "tiba" else None
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop


def route_load(route: Route) -> dict:
    """Perhitungan beban dasar rute: total jarak + total berat/volume shipment."""
    total_jarak = sum((s.jarak_km for s in route.stops), Decimal("0"))
    total_berat = Decimal("0")
    total_volume = Decimal("0")
    for stop in route.stops:
        if stop.shipment is not None:
            total_berat += stop.shipment.total_berat_kg
            total_volume += stop.shipment.total_volume_m3
    return {
        "total_jarak_km": total_jarak,
        "total_berat_kg": total_berat,
        "total_volume_m3": total_volume,
    }


# ----------------------------------------------------------------- internal
def _periksa_kapasitas(
    db: Session,
    organisation_id: uuid.UUID,
    vehicle_id: uuid.UUID | None,
    berat: Decimal,
    volume: Decimal,
) -> None:
    if not vehicle_id:
        return
    vehicle = get_vehicle(db, organisation_id, vehicle_id)
    if vehicle.kapasitas_kg and berat > vehicle.kapasitas_kg:
        raise BusinessRuleError(
            f"Muatan {berat:g} kg melebihi kapasitas "
            f"{vehicle.kapasitas_kg:g} kg armada {vehicle.nama}."
        )
    if vehicle.kapasitas_m3 and volume > vehicle.kapasitas_m3:
        raise BusinessRuleError(
            f"Muatan {volume:g} m³ melebihi kapasitas "
            f"{vehicle.kapasitas_m3:g} m³ armada {vehicle.nama}."
        )


def _set_vehicle_status(db: Session, shipment: Shipment, status: str) -> None:
    if shipment.vehicle is None:
        return
    if status in _STATUS_BERANGKAT:
        shipment.vehicle.status = "dalam_tugas"
    elif status in _STATUS_TIBA or status == "failed":
        shipment.vehicle.status = "tersedia"
    db.add(shipment.vehicle)


def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessRuleError(conflict_message) from exc
