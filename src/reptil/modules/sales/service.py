"""Service sales REPTIL: SO → pengiriman (stok keluar, divalidasi) → faktur penjualan."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from reptil.core.documents import next_number_safe
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.lines import clean_lines
from reptil.core.parsing import to_date
from reptil.modules.inventory.service import record_movement, stock_of
from reptil.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesOrder,
    SalesOrderLine,
)


# ------------------------------------------------------------------- pesanan
def list_orders(db: Session, organisation_id: uuid.UUID, q: str = "", status: str = "") -> list[SalesOrder]:
    stmt = (
        select(SalesOrder)
        .options(selectinload(SalesOrder.lines))
        .where(SalesOrder.organisation_id == organisation_id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(SalesOrder.number.ilike(like))
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    return list(db.execute(stmt.order_by(SalesOrder.created_at.desc())).scalars().all())


def get_order(db: Session, organisation_id: uuid.UUID, order_id: uuid.UUID) -> SalesOrder:
    obj = db.execute(
        select(SalesOrder)
        .options(selectinload(SalesOrder.lines), selectinload(SalesOrder.invoices))
        .where(SalesOrder.id == order_id, SalesOrder.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Pesanan penjualan tidak ditemukan.")
    return obj


def create_order(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    customer_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    tanggal: str | date,
    catatan: str | None,
    lines: list[dict],
) -> SalesOrder:
    bersih = clean_lines(lines, "harga")
    order = SalesOrder(
        organisation_id=organisation_id,
        number=next_number_safe(db, SalesOrder, organisation_id, "SO"),
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        tanggal=to_date(tanggal, "Tanggal"),
        catatan=(catatan or "").strip() or None,
        status="draft",
        created_by=user_id,
    )
    for i, line in enumerate(bersih, start=1):
        order.lines.append(SalesOrderLine(line_no=i, **{k: v for k, v in line.items() if k != "catatan"}))
    order.total = sum((line["subtotal"] for line in bersih), Decimal("0"))
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def deliver_order(
    db: Session, *, organisation_id: uuid.UUID, user_id: uuid.UUID | None, order_id: uuid.UUID
) -> SalesOrder:
    """Kirim pesanan: validasi stok tiap baris, lalu catat mutasi keluar."""
    order = get_order(db, organisation_id, order_id)
    if order.status != "draft":
        raise BusinessRuleError(f"SO {order.number} berstatus '{order.status}' — hanya draft yang bisa dikirim.")

    # Validasi dulu semua baris supaya tidak ada pengiriman separuh jalan
    kurang: list[str] = []
    for line in order.lines:
        tersedia = stock_of(db, organisation_id, line.item_id, order.warehouse_id)
        if tersedia < line.qty:
            kurang.append(f"{line.item.nama}: tersedia {tersedia:g}, diminta {line.qty:g}")
    if kurang:
        raise BusinessRuleError("Stok tidak cukup — " + "; ".join(kurang))

    for line in order.lines:
        record_movement(
            db,
            organisation_id=organisation_id,
            item_id=line.item_id,
            warehouse_id=order.warehouse_id,
            qty=-line.qty,  # negatif = keluar
            ref_type="sales_delivery",
            ref_id=order.id,
            ref_number=order.number,
            note=f"Pengiriman ke {order.customer.nama}",
            user_id=user_id,
        )
    order.status = "delivered"
    order.delivered_at = datetime.now(UTC)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# -------------------------------------------------------------------- faktur
def list_invoices(db: Session, organisation_id: uuid.UUID, q: str = "", status: str = "") -> list[SalesInvoice]:
    stmt = select(SalesInvoice).where(SalesInvoice.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(SalesInvoice.number.ilike(like))
    if status:
        stmt = stmt.where(SalesInvoice.status == status)
    return list(db.execute(stmt.order_by(SalesInvoice.created_at.desc())).scalars().all())


def get_invoice(db: Session, organisation_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
    obj = db.execute(
        select(SalesInvoice)
        .options(selectinload(SalesInvoice.lines), selectinload(SalesInvoice.order))
        .where(SalesInvoice.id == invoice_id, SalesInvoice.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Faktur penjualan tidak ditemukan.")
    return obj


def create_invoice_from_order(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    order_id: uuid.UUID,
    tanggal: str | date,
    jatuh_tempo: str | date | None = None,
    catatan: str | None = None,
) -> SalesInvoice:
    order = get_order(db, organisation_id, order_id)
    if order.status == "invoiced":
        raise BusinessRuleError(f"SO {order.number} sudah difakturkan.")
    if order.status == "cancelled":
        raise BusinessRuleError("SO yang dibatalkan tidak bisa difakturkan.")
    if order.status != "delivered":
        raise BusinessRuleError(
            f"SO {order.number} belum dikirim — kirim barang dulu sebelum membuat faktur."
        )

    invoice = SalesInvoice(
        organisation_id=organisation_id,
        number=next_number_safe(db, SalesInvoice, organisation_id, "FJ"),
        order_id=order.id,
        customer_id=order.customer_id,
        tanggal=to_date(tanggal, "Tanggal faktur"),
        jatuh_tempo=to_date(jatuh_tempo, "Jatuh tempo") if jatuh_tempo else None,
        catatan=(catatan or "").strip() or None,
        status="unpaid",
        created_by=user_id,
        total=order.total,
    )
    for i, line in enumerate(order.lines, start=1):
        invoice.lines.append(
            SalesInvoiceLine(
                line_no=i,
                item_id=line.item_id,
                deskripsi=line.item.nama,
                qty=line.qty,
                harga=line.harga,
                subtotal=line.subtotal,
            )
        )
    order.status = "invoiced"
    db.add_all([invoice, order])
    db.commit()
    db.refresh(invoice)

    # Jurnal otomatis: Dr Piutang / Cr Penjualan (+ Dr HPP / Cr Persediaan)
    from reptil.modules.finance.service import jurnal_faktur_jual

    if jurnal_faktur_jual(db, organisation_id=organisation_id, user_id=user_id, invoice=invoice) is not None:
        db.commit()
    return invoice


def pay_invoice(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    akun_id: uuid.UUID | None = None,
    tanggal: date | None = None,
    metode: str = "transfer",
    referensi: str | None = None,
) -> SalesInvoice:
    """Terima pembayaran piutang (boleh sebagian) — membuat penerimaan + jurnalnya."""
    from reptil.modules.finance.service import akun_kas_default, catat_pembayaran, sisa_faktur

    invoice = get_invoice(db, organisation_id, invoice_id)
    if invoice.status == "cancelled":
        raise BusinessRuleError(f"Faktur {invoice.number} dibatalkan.")
    sisa = sisa_faktur(db, invoice)
    if sisa <= 0:
        raise BusinessRuleError(f"Faktur {invoice.number} sudah lunas.")
    catat_pembayaran(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        arah="masuk",
        faktur_id=invoice.id,
        akun_id=akun_id or akun_kas_default(db, organisation_id).id,
        jumlah=sisa,
        tanggal=tanggal or date.today(),
        metode=metode,
        referensi=referensi,
    )
    db.refresh(invoice)
    return invoice


def summary(db: Session, organisation_id: uuid.UUID) -> dict:
    """Ringkasan untuk dashboard."""
    def count_status(model, status: str) -> int:
        return db.execute(
            select(func.count())
            .select_from(model)
            .where(model.organisation_id == organisation_id, model.status == status)
        ).scalar_one()

    nilai_piutang = db.execute(
        select(func.coalesce(func.sum(SalesInvoice.total), 0)).where(
            SalesInvoice.organisation_id == organisation_id, SalesInvoice.status == "unpaid"
        )
    ).scalar_one()
    from reptil.modules.finance.service import daftar_piutang

    tagihan = daftar_piutang(db, organisation_id)
    return {
        "so_draft": count_status(SalesOrder, "draft"),
        "so_delivered": count_status(SalesOrder, "delivered"),
        "invoice_unpaid": count_status(SalesInvoice, "unpaid") + count_status(SalesInvoice, "partial"),
        "nilai_piutang": sum((t["sisa"] for t in tagihan), Decimal("0")),
    }
