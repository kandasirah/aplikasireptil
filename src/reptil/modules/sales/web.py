"""Halaman web sales: SO, pengiriman, faktur penjualan, export PDF."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.pdf import build_invoice_pdf
from reptil.modules.finance.service import daftar_piutang, pembayaran_faktur, sisa_faktur
from reptil.modules.inventory.service import stock_levels
from reptil.modules.masterdata.service import list_items, list_partners, list_warehouses
from reptil.modules.pengaturan.service import profil_organisasi
from reptil.modules.sales.service import (
    create_invoice_from_order,
    create_order,
    deliver_order,
    get_invoice,
    get_order,
    list_invoices,
    list_orders,
    pay_invoice,
)
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-sales"])


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = "sales.write" if butuh_tulis else "sales.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


def _lines_from_form(form) -> list[dict]:
    lines = []
    for item_id, qty, harga in zip(form.getlist("item_id"), form.getlist("qty"), form.getlist("harga")):
        if item_id:
            lines.append({"item_id": item_id, "qty": qty, "harga": harga})
    return lines


def _stok_per_item(db: Session, organisation_id: uuid.UUID) -> dict:
    """Total stok semua gudang per item — untuk petunjuk di form SO."""
    hasil: dict = {}
    for baris in stock_levels(db, organisation_id):
        hasil[baris["item_id"]] = hasil.get(baris["item_id"], Decimal("0")) + baris["qty"]
    return hasil


# ------------------------------------------------------------------- pesanan
@router.get("/sales/orders", response_class=HTMLResponse, include_in_schema=False)
def orders_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_orders(db, user.organisation_id, q, status))
    return render(request, "sales/orders.html", user, "so",
                  orders=h.items, h=h, q=q, status=status)


@router.get("/sales/orders/new", response_class=HTMLResponse, include_in_schema=False)
def order_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(
        request, "sales/order_form.html", user, "so",
        customers=list_partners(db, user.organisation_id, tipe="customer"),
        warehouses=[w for w in list_warehouses(db, user.organisation_id) if w.is_active],
        items=[i for i in list_items(db, user.organisation_id, aktif=True)],
        stok=_stok_per_item(db, user.organisation_id),
        today=date.today().isoformat(),
    )


@router.post("/sales/orders", include_in_schema=False)
async def order_create(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        order = create_order(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            customer_id=uuid.UUID(str(form.get("customer_id"))),
            warehouse_id=uuid.UUID(str(form.get("warehouse_id"))),
            tanggal=str(form.get("tanggal")),
            catatan=form.get("catatan"),
            lines=_lines_from_form(form),
        )
    except (BusinessRuleError, ValueError, TypeError) as exc:
        return flash_err("/sales/orders/new", str(exc) or "Data SO tidak lengkap.")
    return flash_ok(f"/sales/orders/{order.id}", f"SO {order.number} dibuat.")


@router.get("/sales/orders/{order_id}", response_class=HTMLResponse, include_in_schema=False)
def order_detail(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        order = get_order(db, user.organisation_id, order_id)
    except NotFoundError as exc:
        return flash_err("/sales/orders", str(exc))
    return render(request, "sales/order_detail.html", user, "so", order=order,
                  today=date.today().isoformat(),
                  jatuh_tempo_default=(date.today() + timedelta(days=30)).isoformat())


@router.post("/sales/orders/{order_id}/deliver", include_in_schema=False)
def order_deliver(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        order = deliver_order(db, organisation_id=user.organisation_id, user_id=user.id, order_id=order_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/sales/orders/{order_id}", str(exc))
    return flash_ok(f"/sales/orders/{order.id}", f"SO {order.number} dikirim — stok berkurang.")


# -------------------------------------------------------------------- faktur
@router.get("/sales/invoices", response_class=HTMLResponse, include_in_schema=False)
def invoices_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_invoices(db, user.organisation_id, q, status))
    return render(request, "sales/invoices.html", user, "fj",
                  invoices=h.items, h=h, q=q, status=status,
                  sisa={b["faktur"].id: b["sisa"] for b in daftar_piutang(db, user.organisation_id)})


@router.get("/sales/invoices/{invoice_id}", response_class=HTMLResponse, include_in_schema=False)
def invoice_detail(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        invoice = get_invoice(db, user.organisation_id, invoice_id)
    except NotFoundError as exc:
        return flash_err("/sales/invoices", str(exc))
    return render(request, "sales/invoice_detail.html", user, "fj",
                  invoice=invoice,
                  sisa=sisa_faktur(db, invoice),
                  pembayaran=pembayaran_faktur(db, invoice))


@router.post("/sales/orders/{order_id}/invoice", include_in_schema=False)
async def invoice_create(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    form = await request.form()
    try:
        invoice = create_invoice_from_order(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            order_id=order_id,
            tanggal=str(form.get("tanggal")),
            jatuh_tempo=form.get("jatuh_tempo") or None,
            catatan=form.get("catatan"),
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/sales/orders/{order_id}", str(exc))
    return flash_ok(f"/sales/invoices/{invoice.id}", f"Faktur {invoice.number} dibuat.")


@router.post("/sales/invoices/{invoice_id}/pay", include_in_schema=False)
def invoice_pay(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        invoice = pay_invoice(
            db, organisation_id=user.organisation_id, invoice_id=invoice_id, user_id=user.id
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/sales/invoices/{invoice_id}", str(exc))
    return flash_ok(
        f"/sales/invoices/{invoice.id}", f"Penerimaan pembayaran faktur {invoice.number} dicatat (lunas)."
    )


@router.get("/sales/invoices/{invoice_id}/pdf", include_in_schema=False)
def invoice_pdf(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        invoice = get_invoice(db, user.organisation_id, invoice_id)
    except NotFoundError as exc:
        return flash_err("/sales/invoices", str(exc))

    profil = getattr(user, "profil", None) or profil_organisasi(db, user.organisation_id)
    isi = build_invoice_pdf(
        judul="Faktur Penjualan",
        nomor=invoice.number,
        organisasi={
            "nama": profil.company_name or profil.app_name,
            "alamat": profil.company_address,
            "telepon": profil.company_phone,
            "email": profil.company_email,
            "npwp": profil.company_npwp,
            "logo": profil.company_logo,
        },
        pihak_label="Pelanggan",
        pihak={
            "nama": invoice.customer.nama,
            "alamat": invoice.customer.alamat,
            "telepon": invoice.customer.telepon,
        },
        tanggal=invoice.tanggal,
        jatuh_tempo=invoice.jatuh_tempo,
        referensi=invoice.order.number if invoice.order else None,
        lines=[
            {
                "nama": l.deskripsi or l.item.nama,
                "qty": l.qty,
                "satuan": l.item.satuan,
                "harga": l.harga,
                "subtotal": l.subtotal,
            }
            for l in invoice.lines
        ],
        total=invoice.total,
        catatan=invoice.catatan or profil.invoice_note,
        syarat=profil.invoice_terms,
        status=invoice.status,
    )
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice.number}.pdf"'},
    )
