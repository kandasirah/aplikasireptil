"""Halaman web inventory: saldo stok & kartu stok."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.modules.inventory.service import list_movements, stock_levels
from reptil.modules.masterdata.service import list_items, list_warehouses
from reptil.web.common import flash_err, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-inventory"])
IZIN = "inventory.read"


def _guard(request: Request, db: Session):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    if not has(user, IZIN):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{IZIN}'.")
    return user, None


@router.get("/inventory/stock", response_class=HTMLResponse, include_in_schema=False)
def stock_page(request: Request, q: str = "", warehouse_id: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    wh_id = uuid.UUID(warehouse_id) if warehouse_id else None
    h = halaman(request, stock_levels(db, user.organisation_id, wh_id, q))
    return render(
        request, "inventory/stock.html", user, "stock",
        levels=h.items, h=h,
        warehouses=list_warehouses(db, user.organisation_id),
        q=q, warehouse_id=warehouse_id,
    )


@router.get("/inventory/movements", response_class=HTMLResponse, include_in_schema=False)
def movements_page(
    request: Request,
    item_id: str = "",
    warehouse_id: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db)
    if err:
        return err
    data = list_movements(
        db, user.organisation_id,
        uuid.UUID(item_id) if item_id else None,
        uuid.UUID(warehouse_id) if warehouse_id else None,
        limit=100000,
    )
    kata = q.strip().lower()
    if kata:
        data = [
            m
            for m in data
            if kata in (m.ref_number or "").lower()
            or kata in (m.note or "").lower()
            or kata in (m.ref_type or "").lower()
        ]
    h = halaman(request, data)
    return render(
        request, "inventory/movements.html", user, "mutasi",
        movements=h.items, h=h,
        items=list_items(db, user.organisation_id),
        warehouses=list_warehouses(db, user.organisation_id),
        item_id=item_id, warehouse_id=warehouse_id, q=q,
    )
