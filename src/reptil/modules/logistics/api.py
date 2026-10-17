"""API JSON logistik: pengiriman, armada, ekspedisi, dan rute (Swagger)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import Field
from sqlalchemy.orm import Session

from reptil.api.common import BATAS_BAWAAN, Halaman, SkemaIn, SkemaOut, halaman
from reptil.core.db import get_db
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.logistics import service as svc

router = APIRouter(prefix="/api/v1/logistics", tags=["logistics"])

BACA = require_permission("logistics.read")
TULIS = require_permission("logistics.write")


# ------------------------------------------------------------------ armada
class VehicleIn(SkemaIn):
    kode: str = Field(min_length=1, examples=["TRK-01"])
    nama: str = Field(min_length=1)
    tipe: str = "truk"
    plat: str | None = None
    kapasitas_kg: Decimal = Decimal("0")
    kapasitas_m3: Decimal = Decimal("0")
    pengemudi: str | None = None
    telepon_pengemudi: str | None = None
    status: str = Field(default="tersedia", description="tersedia | dalam_tugas | perbaikan")
    is_active: bool = True


class VehicleOut(SkemaOut):
    id: uuid.UUID
    kode: str
    nama: str
    tipe: str
    plat: str | None
    kapasitas_kg: Decimal
    kapasitas_m3: Decimal
    pengemudi: str | None
    telepon_pengemudi: str | None
    status: str
    is_active: bool


@router.get("/vehicles", response_model=Halaman[VehicleOut], summary="Daftar armada")
def list_vehicles(
    q: str = Query("", description="Cari kode / nama / plat"),
    status: str = Query("", description="tersedia | dalam_tugas | perbaikan"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_vehicles(db, user.organisation_id, q=q, status=status)
    return halaman(items, limit, offset)


@router.post("/vehicles", response_model=VehicleOut, status_code=201, summary="Tambah armada")
def create_vehicle(
    payload: VehicleIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_vehicle(db, user.organisation_id, payload.model_dump())


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut, summary="Detail armada")
def get_vehicle(
    vehicle_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_vehicle(db, user.organisation_id, vehicle_id)


@router.put("/vehicles/{vehicle_id}", response_model=VehicleOut, summary="Ubah armada")
def update_vehicle(
    payload: VehicleIn,
    vehicle_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_vehicle(db, user.organisation_id, payload.model_dump(), vehicle_id)


# --------------------------------------------------------------- ekspedisi
class CarrierIn(SkemaIn):
    kode: str = Field(min_length=1, examples=["EXP-01"])
    nama: str = Field(min_length=1)
    telepon: str | None = None
    tracking_url: str | None = None
    is_active: bool = True


class CarrierOut(SkemaOut):
    id: uuid.UUID
    kode: str
    nama: str
    telepon: str | None
    tracking_url: str | None
    is_active: bool


@router.get("/carriers", response_model=Halaman[CarrierOut], summary="Daftar ekspedisi")
def list_carriers(
    q: str = Query("", description="Cari kode / nama"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_carriers(db, user.organisation_id, q=q)
    return halaman(items, limit, offset)


@router.post("/carriers", response_model=CarrierOut, status_code=201, summary="Tambah ekspedisi")
def create_carrier(
    payload: CarrierIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_carrier(db, user.organisation_id, payload.model_dump())


@router.get("/carriers/{carrier_id}", response_model=CarrierOut, summary="Detail ekspedisi")
def get_carrier(
    carrier_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_carrier(db, user.organisation_id, carrier_id)


@router.put("/carriers/{carrier_id}", response_model=CarrierOut, summary="Ubah ekspedisi")
def update_carrier(
    payload: CarrierIn,
    carrier_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_carrier(db, user.organisation_id, payload.model_dump(), carrier_id)


# --------------------------------------------------------------- pengiriman
class ShipmentLineOut(SkemaOut):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    qty: Decimal
    berat_kg: Decimal
    volume_m3: Decimal


class ShipmentHistoryOut(SkemaOut):
    id: uuid.UUID
    status: str
    note: str | None
    created_at: datetime


class ShipmentOut(SkemaOut):
    id: uuid.UUID
    number: str
    sales_order_id: uuid.UUID | None
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    carrier_id: uuid.UUID | None
    resi: str | None
    alamat_kirim: str | None
    penerima: str | None
    telepon_penerima: str | None
    status: str
    total_berat_kg: Decimal
    total_volume_m3: Decimal
    catatan: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    lines: list[ShipmentLineOut] = Field(default_factory=list)
    history: list[ShipmentHistoryOut] = Field(default_factory=list)


class ShipmentFromOrderIn(SkemaIn):
    order_id: uuid.UUID
    vehicle_id: uuid.UUID | None = None
    carrier_id: uuid.UUID | None = None
    alamat_kirim: str | None = None
    penerima: str | None = None
    telepon_penerima: str | None = None
    resi: str | None = None
    catatan: str | None = None


class ShipmentStatusIn(SkemaIn):
    status: str = Field(description="created | picked_up | in_transit | delivered | failed")
    note: str | None = None


class SiapKirimOut(SkemaOut):
    id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    tanggal: date
    status: str
    total: Decimal


@router.get("/shipments", response_model=Halaman[ShipmentOut], summary="Daftar pengiriman")
def list_shipments(
    q: str = Query("", description="Cari nomor pengiriman / resi / penerima"),
    status: str = Query("", description="created | picked_up | in_transit | delivered | failed"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_shipments(db, user.organisation_id, q=q, status=status)
    return halaman(items, limit, offset)


@router.post(
    "/shipments/from-order",
    response_model=ShipmentOut,
    status_code=201,
    summary="Buat pengiriman dari pesanan penjualan",
)
def create_shipment_from_order(
    payload: ShipmentFromOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.create_shipment_from_order(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        order_id=payload.order_id,
        vehicle_id=payload.vehicle_id,
        carrier_id=payload.carrier_id,
        alamat_kirim=payload.alamat_kirim,
        penerima=payload.penerima,
        telepon_penerima=payload.telepon_penerima,
        resi=payload.resi,
        catatan=payload.catatan,
    )


@router.get("/shipments/{shipment_id}", response_model=ShipmentOut, summary="Detail pengiriman")
def get_shipment(
    shipment_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_shipment(db, user.organisation_id, shipment_id)


@router.post("/shipments/{shipment_id}/status", response_model=ShipmentOut, summary="Ubah status")
def update_shipment_status(
    payload: ShipmentStatusIn,
    shipment_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.update_status(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        shipment_id=shipment_id,
        status=payload.status,
        note=payload.note,
    )


@router.get("/orders-siap-kirim", response_model=list[SiapKirimOut], summary="SO siap dikirim")
def orders_siap_kirim(db: Session = Depends(get_db), user: User = Depends(BACA)) -> list:
    return svc.orders_siap_kirim(db, user.organisation_id)


# -------------------------------------------------------------------- rute
class StopIn(SkemaIn):
    alamat: str = Field(min_length=1)
    shipment_id: uuid.UUID | None = None
    jarak_km: Decimal | None = None
    catatan: str | None = None


class StopStatusIn(SkemaIn):
    status: str = Field(description="pending | tiba | batal")


class StopOut(SkemaOut):
    id: uuid.UUID
    urutan: int
    shipment_id: uuid.UUID | None
    alamat: str
    jarak_km: Decimal
    status: str
    arrived_at: datetime | None
    catatan: str | None


class RouteIn(SkemaIn):
    nama: str = Field(min_length=1)
    tanggal: date | None = None
    vehicle_id: uuid.UUID | None = None
    status: str = Field(default="draft", description="draft | berjalan | selesai")
    catatan: str | None = None


class RouteOut(SkemaOut):
    id: uuid.UUID
    number: str
    nama: str
    tanggal: date
    vehicle_id: uuid.UUID | None
    status: str
    catatan: str | None
    created_at: datetime
    stops: list[StopOut] = Field(default_factory=list)


@router.get("/routes", response_model=Halaman[RouteOut], summary="Daftar rute")
def list_routes(
    q: str = Query("", description="Cari nomor / nama rute"),
    status: str = Query("", description="draft | berjalan | selesai"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_routes(db, user.organisation_id, q=q, status=status)
    return halaman(items, limit, offset)


@router.post("/routes", response_model=RouteOut, status_code=201, summary="Buat rute")
def create_route(
    payload: RouteIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_route(db, user.organisation_id, payload.model_dump(), user_id=user.id)


@router.get("/routes/{route_id}", response_model=RouteOut, summary="Detail rute")
def get_route(
    route_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_route(db, user.organisation_id, route_id)


@router.put("/routes/{route_id}", response_model=RouteOut, summary="Ubah rute")
def update_route(
    payload: RouteIn,
    route_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_route(db, user.organisation_id, payload.model_dump(), route_id, user.id)


@router.post(
    "/routes/{route_id}/stops", response_model=StopOut, status_code=201, summary="Tambah titik rute"
)
def add_stop(
    payload: StopIn,
    route_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.add_stop(
        db,
        organisation_id=user.organisation_id,
        route_id=route_id,
        alamat=payload.alamat,
        shipment_id=payload.shipment_id,
        jarak_km=payload.jarak_km,
        catatan=payload.catatan,
    )


@router.post(
    "/routes/stops/{stop_id}/status", response_model=StopOut, summary="Ubah status titik rute"
)
def update_stop_status(
    payload: StopStatusIn,
    stop_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.update_stop_status(
        db, organisation_id=user.organisation_id, stop_id=stop_id, status=payload.status
    )


@router.get("/routes/{route_id}/load", summary="Beban rute (jarak, berat, volume)")
def route_load(
    route_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    return svc.route_load(svc.get_route(db, user.organisation_id, route_id))


@router.get("/summary", summary="Ringkasan logistik")
def summary(db: Session = Depends(get_db), user: User = Depends(BACA)) -> dict:
    return svc.shipment_summary(db, user.organisation_id)
