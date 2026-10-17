"""Service inventory REPTIL — catat mutasi & hitung saldo stok."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reptil.modules.inventory.models import StockMovement
from reptil.modules.masterdata.models import Item, Warehouse


def record_movement(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    item_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    qty: Decimal,
    ref_type: str,
    ref_id: uuid.UUID | None = None,
    ref_number: str | None = None,
    note: str | None = None,
    user_id: uuid.UUID | None = None,
) -> StockMovement:
    """Catat satu mutasi stok. qty positif = masuk, negatif = keluar."""
    mv = StockMovement(
        organisation_id=organisation_id,
        item_id=item_id,
        warehouse_id=warehouse_id,
        qty=qty,
        ref_type=ref_type,
        ref_id=ref_id,
        ref_number=ref_number,
        note=note,
        created_by=user_id,
    )
    db.add(mv)
    db.flush()
    return mv


def stock_of(db: Session, organisation_id: uuid.UUID, item_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
    """Saldo satu item di satu gudang."""
    total = db.execute(
        select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
            StockMovement.organisation_id == organisation_id,
            StockMovement.item_id == item_id,
            StockMovement.warehouse_id == warehouse_id,
        )
    ).scalar_one()
    return Decimal(total)


def stock_levels(
    db: Session, organisation_id: uuid.UUID, warehouse_id: uuid.UUID | None = None, q: str = ""
) -> list[dict]:
    """Saldo stok per item × gudang (diagregasi dari mutasi)."""
    stmt = (
        select(
            Item.id.label("item_id"),
            Item.sku,
            Item.nama,
            Item.satuan,
            Item.stok_minimum,
            Warehouse.id.label("warehouse_id"),
            Warehouse.nama.label("warehouse_nama"),
            func.coalesce(func.sum(StockMovement.qty), 0).label("qty"),
        )
        .join(StockMovement, StockMovement.item_id == Item.id)
        .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
        .where(StockMovement.organisation_id == organisation_id)
        .group_by(
            Item.id, Item.sku, Item.nama, Item.satuan, Item.stok_minimum,
            Warehouse.id, Warehouse.nama,
        )
    )
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Item.nama.ilike(like) | Item.sku.ilike(like))
    rows = db.execute(stmt.order_by(Item.nama, Warehouse.nama)).all()
    return [
        {
            "item_id": r.item_id,
            "sku": r.sku,
            "nama": r.nama,
            "satuan": r.satuan,
            "warehouse_id": r.warehouse_id,
            "warehouse_nama": r.warehouse_nama,
            "qty": Decimal(r.qty),
            "stok_minimum": Decimal(r.stok_minimum),
            "di_bawah_minimum": Decimal(r.qty) <= Decimal(r.stok_minimum),
        }
        for r in rows
    ]


def list_movements(
    db: Session,
    organisation_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[StockMovement]:
    stmt = select(StockMovement).where(StockMovement.organisation_id == organisation_id)
    if item_id:
        stmt = stmt.where(StockMovement.item_id == item_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    return list(db.execute(stmt.order_by(StockMovement.created_at.desc()).limit(limit)).scalars().all())


def stock_summary(db: Session, organisation_id: uuid.UUID) -> dict:
    """Ringkasan untuk dashboard: jumlah item bergerak & item di bawah minimum."""
    levels = stock_levels(db, organisation_id)
    low = [lv for lv in levels if lv["di_bawah_minimum"]]
    return {
        "baris_stok": len(levels),
        "item_bergerak": len({lv["item_id"] for lv in levels}),
        "item_minimum": len(low),
    }
