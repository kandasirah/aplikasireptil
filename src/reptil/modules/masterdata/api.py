"""API JSON master data: partner, item, dan gudang (Swagger)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import Field
from sqlalchemy.orm import Session

from reptil.api.common import BATAS_BAWAAN, Halaman, SkemaIn, SkemaOut, halaman
from reptil.core.db import get_db
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.masterdata import service as svc

router = APIRouter(prefix="/api/v1/masterdata", tags=["masterdata"])

BACA = require_permission("masterdata.read")
TULIS = require_permission("masterdata.write")


# ------------------------------------------------------------------ partner
class PartnerIn(SkemaIn):
    kode: str = Field(min_length=1, examples=["CUST-001"])
    nama: str = Field(min_length=1, examples=["PT Contoh Jaya"])
    tipe: str = Field(default="customer", description="customer | supplier | both")
    npwp: str | None = None
    email: str | None = None
    telepon: str | None = None
    alamat: str | None = None
    is_active: bool = True


class PartnerOut(SkemaOut):
    id: uuid.UUID
    kode: str
    nama: str
    tipe: str
    npwp: str | None
    email: str | None
    telepon: str | None
    alamat: str | None
    is_active: bool


@router.get("/partners", response_model=Halaman[PartnerOut], summary="Daftar partner")
def list_partners(
    q: str = Query("", description="Cari pada kode / nama"),
    tipe: str = Query("", description="customer | supplier | both"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_partners(db, user.organisation_id, q=q, tipe=tipe)
    return halaman(items, limit, offset)


@router.post("/partners", response_model=PartnerOut, status_code=201, summary="Tambah partner")
def create_partner(
    payload: PartnerIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_partner(db, user.organisation_id, payload.model_dump())


@router.get("/partners/{partner_id}", response_model=PartnerOut, summary="Detail partner")
def get_partner(
    partner_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_partner(db, user.organisation_id, partner_id)


@router.put("/partners/{partner_id}", response_model=PartnerOut, summary="Ubah partner")
def update_partner(
    payload: PartnerIn,
    partner_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_partner(db, user.organisation_id, payload.model_dump(), partner_id)


# --------------------------------------------------------------------- item
class ItemIn(SkemaIn):
    sku: str = Field(min_length=1, examples=["RPT-001"])
    nama: str = Field(min_length=1)
    deskripsi: str | None = None
    tipe: str = Field(default="produk", description="produk | jasa")
    satuan: str = "pcs"
    berat_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    harga_beli: Decimal = Decimal("0")
    harga_jual: Decimal = Decimal("0")
    stok_minimum: Decimal = Decimal("0")
    is_active: bool = True


class ItemOut(SkemaOut):
    id: uuid.UUID
    sku: str
    nama: str
    deskripsi: str | None
    tipe: str
    satuan: str
    berat_kg: Decimal | None
    volume_m3: Decimal | None
    harga_beli: Decimal
    harga_jual: Decimal
    stok_minimum: Decimal
    is_active: bool


@router.get("/items", response_model=Halaman[ItemOut], summary="Daftar item")
def list_items(
    q: str = Query("", description="Cari pada SKU / nama"),
    aktif: bool | None = Query(None, description="Filter status aktif"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_items(db, user.organisation_id, q=q, aktif=aktif)
    return halaman(items, limit, offset)


@router.post("/items", response_model=ItemOut, status_code=201, summary="Tambah item")
def create_item(
    payload: ItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_item(db, user.organisation_id, payload.model_dump())


@router.get("/items/{item_id}", response_model=ItemOut, summary="Detail item")
def get_item(
    item_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_item(db, user.organisation_id, item_id)


@router.put("/items/{item_id}", response_model=ItemOut, summary="Ubah item")
def update_item(
    payload: ItemIn,
    item_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_item(db, user.organisation_id, payload.model_dump(), item_id)


# ----------------------------------------------------------------- gudang
class WarehouseIn(SkemaIn):
    kode: str = Field(min_length=1, examples=["GDG-01"])
    nama: str = Field(min_length=1)
    alamat: str | None = None
    is_default: bool = False
    is_active: bool = True


class WarehouseOut(SkemaOut):
    id: uuid.UUID
    kode: str
    nama: str
    alamat: str | None
    is_default: bool
    is_active: bool


@router.get("/warehouses", response_model=Halaman[WarehouseOut], summary="Daftar gudang")
def list_warehouses(
    q: str = Query("", description="Cari pada kode / nama"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_warehouses(db, user.organisation_id, q=q)
    return halaman(items, limit, offset)


@router.post("/warehouses", response_model=WarehouseOut, status_code=201, summary="Tambah gudang")
def create_warehouse(
    payload: WarehouseIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_warehouse(db, user.organisation_id, payload.model_dump())


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseOut, summary="Detail gudang")
def get_warehouse(
    warehouse_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_warehouse(db, user.organisation_id, warehouse_id)


@router.put("/warehouses/{warehouse_id}", response_model=WarehouseOut, summary="Ubah gudang")
def update_warehouse(
    payload: WarehouseIn,
    warehouse_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.save_warehouse(db, user.organisation_id, payload.model_dump(), warehouse_id)
