"""Halaman web master data: Partner, Item, Gudang."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.modules.masterdata.service import (
    get_item,
    get_partner,
    get_warehouse,
    list_items,
    list_partners,
    list_warehouses,
    save_item,
    save_partner,
    save_warehouse,
)
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-master"])
KODE = "masterdata"


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    """Return (user, response_error). response_error != None berarti harus dibalas langsung."""
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = f"{KODE}.write" if butuh_tulis else f"{KODE}.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


# ------------------------------------------------------------------- partner
@router.get("/master/partners", response_class=HTMLResponse, include_in_schema=False)
def partners_page(request: Request, q: str = "", tipe: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_partners(db, user.organisation_id, q, tipe))
    return render(
        request, "master/partners.html", user, "partners",
        partners=h.items, h=h, q=q, tipe=tipe,
    )


@router.get("/master/partners/new", response_class=HTMLResponse, include_in_schema=False)
def partner_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(request, "master/partner_form.html", user, "partners", partner=None, is_new=True)


@router.get("/master/partners/{partner_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def partner_edit(partner_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        partner = get_partner(db, user.organisation_id, partner_id)
    except NotFoundError as exc:
        return flash_err("/master/partners", str(exc))
    return render(request, "master/partner_form.html", user, "partners", partner=partner, is_new=False)


@router.post("/master/partners", include_in_schema=False)
async def partner_create(request: Request, db: Session = Depends(get_db)):
    return await _partner_save(request, db, None)


@router.post("/master/partners/{partner_id}", include_in_schema=False)
async def partner_update(partner_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    return await _partner_save(request, db, partner_id)


async def _partner_save(request: Request, db: Session, partner_id: uuid.UUID | None):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    tujuan = "/master/partners" if partner_id is None else f"/master/partners/{partner_id}"
    try:
        partner = save_partner(db, user.organisation_id, dict(form), partner_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"{tujuan}/edit" if partner_id else "/master/partners/new", str(exc))
    return flash_ok("/master/partners", f"Partner {partner.kode} disimpan.")


# ---------------------------------------------------------------------- item
@router.get("/master/items", response_class=HTMLResponse, include_in_schema=False)
def items_page(
    request: Request, q: str = "", tipe: str = "", status: str = "", db: Session = Depends(get_db)
):
    user, err = _guard(request, db)
    if err:
        return err
    filter_aktif = {"aktif": True, "nonaktif": False}.get(status)
    data = list_items(db, user.organisation_id, q, aktif=filter_aktif)
    if tipe in ("produk", "jasa"):
        data = [i for i in data if i.tipe == tipe]
    h = halaman(request, data)
    return render(request, "master/items.html", user, "items",
                  items=h.items, h=h, q=q, tipe=tipe, status=status)


@router.get("/master/items/new", response_class=HTMLResponse, include_in_schema=False)
def item_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(request, "master/item_form.html", user, "items", item=None, is_new=True)


@router.get("/master/items/{item_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def item_edit(item_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        item = get_item(db, user.organisation_id, item_id)
    except NotFoundError as exc:
        return flash_err("/master/items", str(exc))
    return render(request, "master/item_form.html", user, "items", item=item, is_new=False)


@router.post("/master/items", include_in_schema=False)
async def item_create(request: Request, db: Session = Depends(get_db)):
    return await _item_save(request, db, None)


@router.post("/master/items/{item_id}", include_in_schema=False)
async def item_update(item_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    return await _item_save(request, db, item_id)


async def _item_save(request: Request, db: Session, item_id: uuid.UUID | None):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        item = save_item(db, user.organisation_id, dict(form), item_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/master/items/{item_id}/edit" if item_id else "/master/items/new", str(exc))
    return flash_ok("/master/items", f"Item {item.sku} disimpan.")


# ----------------------------------------------------------------- warehouse
@router.get("/master/warehouses", response_class=HTMLResponse, include_in_schema=False)
def warehouses_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_warehouses(db, user.organisation_id, q))
    return render(request, "master/warehouses.html", user, "warehouses",
                  warehouses=h.items, h=h, q=q)


@router.get("/master/warehouses/new", response_class=HTMLResponse, include_in_schema=False)
def warehouse_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(request, "master/warehouse_form.html", user, "warehouses", warehouse=None, is_new=True)


@router.get("/master/warehouses/{warehouse_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def warehouse_edit(warehouse_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        warehouse = get_warehouse(db, user.organisation_id, warehouse_id)
    except NotFoundError as exc:
        return flash_err("/master/warehouses", str(exc))
    return render(request, "master/warehouse_form.html", user, "warehouses", warehouse=warehouse, is_new=False)


@router.post("/master/warehouses", include_in_schema=False)
async def warehouse_create(request: Request, db: Session = Depends(get_db)):
    return await _warehouse_save(request, db, None)


@router.post("/master/warehouses/{warehouse_id}", include_in_schema=False)
async def warehouse_update(warehouse_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    return await _warehouse_save(request, db, warehouse_id)


async def _warehouse_save(request: Request, db: Session, warehouse_id: uuid.UUID | None):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        warehouse = save_warehouse(db, user.organisation_id, dict(form), warehouse_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(
            f"/master/warehouses/{warehouse_id}/edit" if warehouse_id else "/master/warehouses/new", str(exc)
        )
    return flash_ok("/master/warehouses", f"Gudang {warehouse.kode} disimpan.")
