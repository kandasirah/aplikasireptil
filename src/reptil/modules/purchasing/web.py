"""Halaman web purchasing: PO, penerimaan barang, faktur pembelian, export PDF."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.pdf import build_invoice_pdf
from reptil.modules.finance.service import daftar_utang, pembayaran_faktur, sisa_faktur
from reptil.modules.masterdata.service import list_items, list_partners, list_warehouses
from reptil.modules.pengaturan.service import profil_organisasi
from reptil.modules.purchasing.service import (
    create_invoice_from_order,
    create_order,
    get_invoice,
    get_order,
    list_invoices,
    list_orders,
    pay_invoice,
    receive_order,
)
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-purchasing"])


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = "purchasing.write" if butuh_tulis else "purchasing.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


def _lines_from_form(form) -> list[dict]:
    lines = []
    for item_id, qty, harga in zip(form.getlist("item_id"), form.getlist("qty"), form.getlist("harga")):
        if item_id:
            lines.append({"item_id": item_id, "qty": qty, "harga": harga})
    return lines


# ------------------------------------------------------------------- pesanan
@router.get("/purchases/orders", response_class=HTMLResponse, include_in_schema=False)
def orders_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_orders(db, user.organisation_id, q, status))
    return render(request, "purchases/orders.html", user, "po",
                  orders=h.items, h=h, q=q, status=status)


@router.get("/purchases/orders/new", response_class=HTMLResponse, include_in_schema=False)
def order_new(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    return render(
        request, "purchases/order_form.html", user, "po",
        suppliers=list_partners(db, user.organisation_id, tipe="supplier"),
        warehouses=[w for w in list_warehouses(db, user.organisation_id) if w.is_active],
        items=[i for i in list_items(db, user.organisation_id, aktif=True)],
        today=date.today().isoformat(),
    )


@router.post("/purchases/orders", include_in_schema=False)
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
            supplier_id=uuid.UUID(str(form.get("supplier_id"))),
            warehouse_id=uuid.UUID(str(form.get("warehouse_id"))),
            tanggal=str(form.get("tanggal")),
            catatan=form.get("catatan"),
            lines=_lines_from_form(form),
        )
    except (BusinessRuleError, ValueError, TypeError) as exc:
        return flash_err("/purchases/orders/new", str(exc) or "Data PO tidak lengkap.")
    return flash_ok(f"/purchases/orders/{order.id}", f"PO {order.number} dibuat.")


@router.get("/purchases/orders/{order_id}", response_class=HTMLResponse, include_in_schema=False)
def order_detail(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        order = get_order(db, user.organisation_id, order_id)
    except NotFoundError as exc:
        return flash_err("/purchases/orders", str(exc))
    return render(request, "purchases/order_detail.html", user, "po", order=order,
                  today=date.today().isoformat(),
                  jatuh_tempo_default=(date.today() + timedelta(days=30)).isoformat())


@router.post("/purchases/orders/{order_id}/receive", include_in_schema=False)
def order_receive(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        order = receive_order(db, organisation_id=user.organisation_id, user_id=user.id, order_id=order_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/purchases/orders/{order_id}", str(exc))
    return flash_ok(f"/purchases/orders/{order.id}", f"Barang PO {order.number} diterima — stok bertambah.")


# -------------------------------------------------------------------- faktur
@router.get("/purchases/invoices", response_class=HTMLResponse, include_in_schema=False)
def invoices_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, list_invoices(db, user.organisation_id, q, status))
    return render(request, "purchases/invoices.html", user, "fb",
                  invoices=h.items, h=h, q=q, status=status,
                  sisa={b["faktur"].id: b["sisa"] for b in daftar_utang(db, user.organisation_id)})


@router.get("/purchases/invoices/{invoice_id}", response_class=HTMLResponse, include_in_schema=False)
def invoice_detail(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        invoice = get_invoice(db, user.organisation_id, invoice_id)
    except NotFoundError as exc:
        return flash_err("/purchases/invoices", str(exc))
    return render(request, "purchases/invoice_detail.html", user, "fb",
                  invoice=invoice,
                  sisa=sisa_faktur(db, invoice),
                  pembayaran=pembayaran_faktur(db, invoice))


@router.post("/purchases/orders/{order_id}/invoice", include_in_schema=False)
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
            supplier_ref=form.get("supplier_ref"),
            catatan=form.get("catatan"),
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/purchases/orders/{order_id}", str(exc))
    return flash_ok(f"/purchases/invoices/{invoice.id}", f"Faktur {invoice.number} dibuat.")


@router.post("/purchases/invoices/{invoice_id}/pay", include_in_schema=False)
def invoice_pay(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        invoice = pay_invoice(
            db, organisation_id=user.organisation_id, invoice_id=invoice_id, user_id=user.id
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/purchases/invoices/{invoice_id}", str(exc))
    return flash_ok(
        f"/purchases/invoices/{invoice.id}", f"Pembayaran faktur {invoice.number} dicatat (lunas)."
    )


@router.get("/purchases/invoices/{invoice_id}/pdf", include_in_schema=False)
def invoice_pdf(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        invoice = get_invoice(db, user.organisation_id, invoice_id)
    except NotFoundError as exc:
        return flash_err("/purchases/invoices", str(exc))

    profil = getattr(user, "profil", None) or profil_organisasi(db, user.organisation_id)
    isi = build_invoice_pdf(
        judul="Faktur Pembelian",
        nomor=invoice.number,
        organisasi={
            "nama": profil.company_name or profil.app_name,
            "alamat": profil.company_address,
            "telepon": profil.company_phone,
            "email": profil.company_email,
            "npwp": profil.company_npwp,
            "logo": profil.company_logo,
        },
        pihak_label="Pemasok",
        pihak={
            "nama": invoice.supplier.nama,
            "alamat": invoice.supplier.alamat,
            "telepon": invoice.supplier.telepon,
        },
        tanggal=invoice.tanggal,
        jatuh_tempo=invoice.jatuh_tempo,
        referensi=invoice.order.number if invoice.order else invoice.supplier_ref,
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
