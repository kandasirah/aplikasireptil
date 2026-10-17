"""Halaman web logistik: pengiriman, armada, ekspedisi, dan rute."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.modules.logistics.models import SHIPMENT_STATUSES
from reptil.modules.logistics.service import (
    add_stop,
    create_shipment_from_order,
    get_carrier,
    get_route,
    get_shipment,
    get_vehicle,
    list_carriers,
    list_routes,
    list_shipments,
    list_vehicles,
    orders_siap_kirim,
    route_load,
    save_carrier,
    save_route,
    save_vehicle,
    shipment_summary,
    update_status,
    update_stop_status,
)
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-logistics"])


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = "logistics.write" if butuh_tulis else "logistics.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


# --------------------------------------------------------------- pengiriman
@router.get("/logistics/shipments", response_class=HTMLResponse, include_in_schema=False)
def shipments_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_shipments(db, user.organisation_id, q, status))
    return render(
        request,
        "logistics/shipments.html",
        user,
        "shipments",
        shipments=h.items,
        h=h,
        ringkasan=shipment_summary(db, user.organisation_id),
        q=q,
        status=status,
    )


@router.get("/logistics/shipments/new", response_class=HTMLResponse, include_in_schema=False)
def shipment_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(
        request,
        "logistics/shipment_form.html",
        user,
        "shipments",
        orders=orders_siap_kirim(db, user.organisation_id),
        vehicles=[v for v in list_vehicles(db, user.organisation_id) if v.is_active],
        carriers=[c for c in list_carriers(db, user.organisation_id) if c.is_active],
    )


@router.post("/logistics/shipments", include_in_schema=False)
async def shipment_create(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        shipment = create_shipment_from_order(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            order_id=uuid.UUID(str(form.get("sales_order_id"))),
            vehicle_id=uuid.UUID(str(form["vehicle_id"])) if form.get("vehicle_id") else None,
            carrier_id=uuid.UUID(str(form["carrier_id"])) if form.get("carrier_id") else None,
            alamat_kirim=form.get("alamat_kirim"),
            penerima=form.get("penerima"),
            telepon_penerima=form.get("telepon_penerima"),
            resi=form.get("resi"),
            catatan=form.get("catatan"),
        )
    except (BusinessRuleError, ValueError, TypeError) as exc:
        return flash_err("/logistics/shipments/new", str(exc) or "Data pengiriman tidak lengkap.")
    return flash_ok(f"/logistics/shipments/{shipment.id}", f"Pengiriman {shipment.number} dibuat.")


@router.get(
    "/logistics/shipments/{shipment_id}", response_class=HTMLResponse, include_in_schema=False
)
def shipment_detail(shipment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        shipment = get_shipment(db, user.organisation_id, shipment_id)
    except NotFoundError as exc:
        return flash_err("/logistics/shipments", str(exc))
    return render(
        request,
        "logistics/shipment_detail.html",
        user,
        "shipments",
        shipment=shipment,
        statuses=SHIPMENT_STATUSES,
    )


@router.post("/logistics/shipments/{shipment_id}/status", include_in_schema=False)
async def shipment_status(shipment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        update_status(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            shipment_id=shipment_id,
            status=str(form.get("status") or ""),
            note=form.get("note"),
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/logistics/shipments/{shipment_id}", str(exc))
    return flash_ok(f"/logistics/shipments/{shipment_id}", "Status pengiriman diperbarui.")


# ------------------------------------------------------------------- armada
@router.get("/logistics/vehicles", response_class=HTMLResponse, include_in_schema=False)
def vehicles_page(
    request: Request, q: str = "", status: str = "", edit: str = "", db: Session = Depends(get_db)
):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        edit_vehicle = get_vehicle(db, user.organisation_id, uuid.UUID(edit)) if edit else None
    except (ValueError, NotFoundError):
        edit_vehicle = None
    h = halaman(request, list_vehicles(db, user.organisation_id, q, status), abaikan=("edit",))
    return render(
        request,
        "logistics/vehicles.html",
        user,
        "vehicles",
        vehicles=h.items,
        h=h,
        edit_vehicle=edit_vehicle,
        q=q,
        status=status,
    )


@router.post("/logistics/vehicles", include_in_schema=False)
async def vehicle_save(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    data = {
        k: form.get(k)
        for k in (
            "kode",
            "nama",
            "tipe",
            "plat",
            "kapasitas_kg",
            "kapasitas_m3",
            "pengemudi",
            "telepon_pengemudi",
            "status",
        )
    }
    data["is_active"] = form.get("is_active") is not None
    vehicle_id = form.get("vehicle_id")
    try:
        save_vehicle(
            db,
            user.organisation_id,
            data,
            uuid.UUID(vehicle_id) if vehicle_id else None,
        )
    except BusinessRuleError as exc:
        return flash_err("/logistics/vehicles", str(exc))
    return flash_ok("/logistics/vehicles", "Armada disimpan.")


# --------------------------------------------------------------- ekspedisi
@router.get("/logistics/carriers", response_class=HTMLResponse, include_in_schema=False)
def carriers_page(request: Request, q: str = "", edit: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        edit_carrier = get_carrier(db, user.organisation_id, uuid.UUID(edit)) if edit else None
    except (ValueError, NotFoundError):
        edit_carrier = None
    h = halaman(request, list_carriers(db, user.organisation_id, q), abaikan=("edit",))
    return render(
        request,
        "logistics/carriers.html",
        user,
        "carriers",
        carriers=h.items,
        h=h,
        edit_carrier=edit_carrier,
        q=q,
    )


@router.post("/logistics/carriers", include_in_schema=False)
async def carrier_save(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    data = {k: form.get(k) for k in ("kode", "nama", "telepon", "tracking_url")}
    data["is_active"] = form.get("is_active") is not None
    carrier_id = form.get("carrier_id")
    try:
        save_carrier(
            db,
            user.organisation_id,
            data,
            uuid.UUID(carrier_id) if carrier_id else None,
        )
    except BusinessRuleError as exc:
        return flash_err("/logistics/carriers", str(exc))
    return flash_ok("/logistics/carriers", "Ekspedisi disimpan.")


# -------------------------------------------------------------------- rute
@router.get("/logistics/routes", response_class=HTMLResponse, include_in_schema=False)
def routes_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_routes(db, user.organisation_id, q, status))
    return render(
        request,
        "logistics/routes.html",
        user,
        "routes",
        routes=h.items,
        h=h,
        vehicles=[v for v in list_vehicles(db, user.organisation_id) if v.is_active],
        today=date.today().isoformat(),
        q=q,
        status=status,
    )


@router.post("/logistics/routes", include_in_schema=False)
async def route_save(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    route_id = form.get("route_id")
    try:
        route = save_route(
            db,
            user.organisation_id,
            {
                "nama": form.get("nama"),
                "tanggal": form.get("tanggal"),
                "vehicle_id": form.get("vehicle_id"),
                "status": form.get("status"),
                "catatan": form.get("catatan"),
            },
            uuid.UUID(str(route_id)) if route_id else None,
            user_id=user.id,
        )
    except BusinessRuleError as exc:
        return flash_err("/logistics/routes", str(exc))
    return flash_ok(f"/logistics/routes/{route.id}", f"Rute {route.number} disimpan.")


@router.get("/logistics/routes/{route_id}", response_class=HTMLResponse, include_in_schema=False)
def route_detail(route_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        route = get_route(db, user.organisation_id, route_id)
    except NotFoundError as exc:
        return flash_err("/logistics/routes", str(exc))
    return render(
        request,
        "logistics/route_detail.html",
        user,
        "routes",
        route=route,
        load=route_load(route),
        shipments=list_shipments(db, user.organisation_id),
    )


@router.post("/logistics/routes/{route_id}/stops", include_in_schema=False)
async def route_add_stop(route_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    shipment_id = form.get("shipment_id")
    try:
        add_stop(
            db,
            organisation_id=user.organisation_id,
            route_id=route_id,
            alamat=str(form.get("alamat") or ""),
            shipment_id=uuid.UUID(str(shipment_id)) if shipment_id else None,
            jarak_km=form.get("jarak_km"),
            catatan=form.get("catatan"),
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/logistics/routes/{route_id}", str(exc))
    return flash_ok(f"/logistics/routes/{route_id}", "Titik berhenti ditambahkan.")


@router.post("/logistics/stops/{stop_id}/status", include_in_schema=False)
async def stop_status(stop_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        stop = update_stop_status(
            db,
            organisation_id=user.organisation_id,
            stop_id=stop_id,
            status=str(form.get("status") or ""),
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err("/logistics/routes", str(exc))
    return flash_ok(f"/logistics/routes/{stop.route_id}", "Status titik diperbarui.")


__all__ = ["router"]
