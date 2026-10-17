"""API JSON pembelian: pesanan, penerimaan, faktur, dan pembayaran (Swagger)."""

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
from reptil.modules.purchasing import service as svc

router = APIRouter(prefix="/api/v1/purchases", tags=["purchases"])

BACA = require_permission("purchasing.read")
TULIS = require_permission("purchasing.write")


# ------------------------------------------------------------------ pesanan
class LineIn(SkemaIn):
    item_id: uuid.UUID
    qty: Decimal = Field(gt=0)
    harga: Decimal = Field(default=Decimal("0"), ge=0)
    catatan: str | None = None


class OrderLineOut(SkemaOut):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    qty: Decimal
    harga: Decimal
    subtotal: Decimal
    catatan: str | None


class OrderIn(SkemaIn):
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    tanggal: date
    catatan: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class OrderOut(SkemaOut):
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    tanggal: date
    status: str
    catatan: str | None
    total: Decimal
    received_at: datetime | None
    created_at: datetime
    lines: list[OrderLineOut] = Field(default_factory=list)


@router.get("/orders", response_model=Halaman[OrderOut], summary="Daftar pesanan pembelian")
def list_orders(
    q: str = Query("", description="Cari nomor PO"),
    status: str = Query("", description="draft | received | cancelled"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_orders(db, user.organisation_id, q=q, status=status)
    return halaman(items, limit, offset)


@router.post("/orders", response_model=OrderOut, status_code=201, summary="Buat pesanan pembelian")
def create_order(
    payload: OrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.create_order(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        supplier_id=payload.supplier_id,
        warehouse_id=payload.warehouse_id,
        tanggal=payload.tanggal,
        catatan=payload.catatan,
        lines=[line.model_dump() for line in payload.lines],
    )


@router.get("/orders/{order_id}", response_model=OrderOut, summary="Detail pesanan pembelian")
def get_order(
    order_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_order(db, user.organisation_id, order_id)


@router.post(
    "/orders/{order_id}/receive",
    response_model=OrderOut,
    summary="Terima barang (stok masuk)",
)
def receive_order(
    order_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.receive_order(
        db, organisation_id=user.organisation_id, user_id=user.id, order_id=order_id
    )


# ------------------------------------------------------------------- faktur
class InvoiceLineOut(SkemaOut):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    deskripsi: str | None
    qty: Decimal
    harga: Decimal
    subtotal: Decimal


class InvoiceIn(SkemaIn):
    order_id: uuid.UUID
    tanggal: date
    jatuh_tempo: date | None = None
    supplier_ref: str | None = Field(default=None, description="Nomor faktur dari supplier")


class InvoiceOut(SkemaOut):
    id: uuid.UUID
    number: str
    order_id: uuid.UUID | None
    supplier_id: uuid.UUID
    supplier_ref: str | None
    tanggal: date
    jatuh_tempo: date | None
    status: str
    catatan: str | None
    total: Decimal
    paid_at: datetime | None
    created_at: datetime
    lines: list[InvoiceLineOut] = Field(default_factory=list)


class PayIn(SkemaIn):
    akun_id: uuid.UUID | None = Field(default=None, description="Akun kas/bank; kosong = bawaan")
    tanggal: date | None = None
    metode: str = "transfer"
    referensi: str | None = None


@router.get("/invoices", response_model=Halaman[InvoiceOut], summary="Daftar faktur pembelian")
def list_invoices(
    q: str = Query("", description="Cari nomor faktur"),
    status: str = Query("", description="unpaid | partial | paid | cancelled"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_invoices(db, user.organisation_id, q=q, status=status)
    return halaman(items, limit, offset)


@router.post(
    "/invoices",
    response_model=InvoiceOut,
    status_code=201,
    summary="Buat faktur pembelian dari pesanan",
)
def create_invoice(
    payload: InvoiceIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.create_invoice_from_order(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        order_id=payload.order_id,
        tanggal=payload.tanggal,
        jatuh_tempo=payload.jatuh_tempo,
        supplier_ref=payload.supplier_ref,
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, summary="Detail faktur pembelian")
def get_invoice(
    invoice_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_invoice(db, user.organisation_id, invoice_id)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut, summary="Bayar faktur")
def pay_invoice(
    invoice_id: uuid.UUID = Path(...),
    payload: PayIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    data = payload or PayIn()
    return svc.pay_invoice(
        db,
        organisation_id=user.organisation_id,
        invoice_id=invoice_id,
        user_id=user.id,
        akun_id=data.akun_id,
        tanggal=data.tanggal,
        metode=data.metode,
        referensi=data.referensi,
    )


@router.get("/summary", summary="Ringkasan pembelian")
def summary(db: Session = Depends(get_db), user: User = Depends(BACA)) -> dict:
    return svc.summary(db, user.organisation_id)
