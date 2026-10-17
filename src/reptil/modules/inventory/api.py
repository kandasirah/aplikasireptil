"""API JSON persediaan: saldo stok, kartu stok, dan penyesuaian (Swagger)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.orm import Session

from reptil.api.common import BATAS_BAWAAN, Halaman, SkemaIn, SkemaOut, halaman
from reptil.core.db import get_db
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.inventory import service as svc

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

BACA = require_permission("inventory.read")
TULIS = require_permission("inventory.write")


class StockOut(SkemaOut):
    item_id: uuid.UUID
    sku: str
    nama: str
    satuan: str
    warehouse_id: uuid.UUID
    warehouse_nama: str
    qty: Decimal
    stok_minimum: Decimal
    di_bawah_minimum: bool


class MovementOut(SkemaOut):
    id: uuid.UUID
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty: Decimal
    ref_type: str
    ref_id: uuid.UUID | None
    ref_number: str | None
    note: str | None
    created_at: datetime


class PenyesuaianIn(SkemaIn):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty: Decimal = Field(description="Positif = stok masuk, negatif = stok keluar")
    ref_number: str | None = None
    note: str | None = None


@router.get("/stock", response_model=Halaman[StockOut], summary="Saldo stok per item dan gudang")
def stock_levels(
    q: str = Query("", description="Cari pada SKU / nama item"),
    warehouse_id: uuid.UUID | None = None,
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.stock_levels(db, user.organisation_id, warehouse_id=warehouse_id, q=q)
    return halaman(items, limit, offset)


@router.get("/movements", response_model=Halaman[MovementOut], summary="Kartu stok (mutasi)")
def list_movements(
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_movements(
        db, user.organisation_id, item_id=item_id, warehouse_id=warehouse_id, limit=100_000
    )
    return halaman(items, limit, offset)


@router.get("/summary", summary="Ringkasan persediaan")
def stock_summary(db: Session = Depends(get_db), user: User = Depends(BACA)) -> dict:
    return svc.stock_summary(db, user.organisation_id)


@router.post(
    "/adjustments",
    response_model=MovementOut,
    status_code=201,
    summary="Catat penyesuaian stok",
)
def create_adjustment(
    payload: PenyesuaianIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    mv = svc.record_movement(
        db,
        organisation_id=user.organisation_id,
        item_id=payload.item_id,
        warehouse_id=payload.warehouse_id,
        qty=payload.qty,
        ref_type="adjustment",
        ref_number=payload.ref_number,
        note=payload.note,
        user_id=user.id,
    )
    db.commit()
    db.refresh(mv)
    return mv


__all__ = ["router"]
