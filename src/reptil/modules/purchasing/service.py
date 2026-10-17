"""Service purchasing REPTIL: PO → penerimaan barang (stok masuk) → faktur pembelian."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reptil.core.documents import next_number_safe
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.lines import clean_lines
from reptil.core.parsing import to_date
from reptil.modules.inventory.service import record_movement
from reptil.modules.purchasing.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)


# ------------------------------------------------------------------- pesanan
def list_orders(db: Session, organisation_id: uuid.UUID, q: str = "", status: str = "") -> list[PurchaseOrder]:
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines))
        .where(PurchaseOrder.organisation_id == organisation_id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(PurchaseOrder.number.ilike(like))
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    return list(db.execute(stmt.order_by(PurchaseOrder.created_at.desc())).scalars().all())


def get_order(db: Session, organisation_id: uuid.UUID, order_id: uuid.UUID) -> PurchaseOrder:
    obj = db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.invoices))
        .where(PurchaseOrder.id == order_id, PurchaseOrder.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Pesanan pembelian tidak ditemukan.")
    return obj


def create_order(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    supplier_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    tanggal: str | date,
    catatan: str | None,
    lines: list[dict],
) -> PurchaseOrder:
    bersih = clean_lines(lines, "harga")
    order = PurchaseOrder(
        organisation_id=organisation_id,
        number=next_number_safe(db, PurchaseOrder, organisation_id, "PO"),
        supplier_id=supplier_id,
        warehouse_id=warehouse_id,
        tanggal=to_date(tanggal, "Tanggal"),
        catatan=(catatan or "").strip() or None,
        status="draft",
        created_by=user_id,
    )
    for i, line in enumerate(bersih, start=1):
        order.lines.append(PurchaseOrderLine(line_no=i, **line))
    order.total = sum((line["subtotal"] for line in bersih), Decimal("0"))
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def receive_order(db: Session, *, organisation_id: uuid.UUID, user_id: uuid.UUID | None, order_id: uuid.UUID) -> PurchaseOrder:
    """Terima barang: status PO → received dan stok masuk ke gudang PO."""
    order = get_order(db, organisation_id, order_id)
    if order.status != "draft":
        raise BusinessRuleError(f"PO {order.number} berstatus '{order.status}' — hanya draft yang bisa diterima.")
    if not order.lines:
        raise BusinessRuleError("PO tanpa baris item tidak bisa diterima.")

    for line in order.lines:
        record_movement(
            db,
            organisation_id=organisation_id,
            item_id=line.item_id,
            warehouse_id=order.warehouse_id,
            qty=line.qty,  # positif = masuk
            ref_type="purchase_receipt",
            ref_id=order.id,
            ref_number=order.number,
            note=f"Penerimaan barang dari {order.supplier.nama}",
            user_id=user_id,
        )
    order.status = "received"
    order.received_at = datetime.now(UTC)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# -------------------------------------------------------------------- faktur
def list_invoices(db: Session, organisation_id: uuid.UUID, q: str = "", status: str = "") -> list[PurchaseInvoice]:
    stmt = select(PurchaseInvoice).where(PurchaseInvoice.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(PurchaseInvoice.number.ilike(like))
    if status:
        stmt = stmt.where(PurchaseInvoice.status == status)
    return list(db.execute(stmt.order_by(PurchaseInvoice.created_at.desc())).scalars().all())


def get_invoice(db: Session, organisation_id: uuid.UUID, invoice_id: uuid.UUID) -> PurchaseInvoice:
    obj = db.execute(
        select(PurchaseInvoice)
        .options(selectinload(PurchaseInvoice.lines), selectinload(PurchaseInvoice.order))
        .where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Faktur pembelian tidak ditemukan.")
    return obj


def create_invoice_from_order(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    order_id: uuid.UUID,
    tanggal: str | date,
    jatuh_tempo: str | date | None = None,
    supplier_ref: str | None = None,
    catatan: str | None = None,
) -> PurchaseInvoice:
    order = get_order(db, organisation_id, order_id)
    if order.status == "invoiced":
        raise BusinessRuleError(f"PO {order.number} sudah difakturkan.")
    if order.status == "cancelled":
        raise BusinessRuleError("PO yang dibatalkan tidak bisa difakturkan.")
    if order.status != "received":
        raise BusinessRuleError(
            f"PO {order.number} belum diterima — terima barang dulu sebelum membuat faktur."
        )

    invoice = PurchaseInvoice(
        organisation_id=organisation_id,
        number=next_number_safe(db, PurchaseInvoice, organisation_id, "FB"),
        order_id=order.id,
        supplier_id=order.supplier_id,
        supplier_ref=(supplier_ref or "").strip() or None,
        tanggal=to_date(tanggal, "Tanggal faktur"),
        jatuh_tempo=to_date(jatuh_tempo, "Jatuh tempo", default=None) if jatuh_tempo else None,
        catatan=(catatan or "").strip() or None,
        status="unpaid",
        created_by=user_id,
        total=order.total,
    )
    for i, line in enumerate(order.lines, start=1):
        invoice.lines.append(
            PurchaseInvoiceLine(
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

    # Jurnal otomatis: Dr Persediaan / Cr Utang Usaha
    from reptil.modules.finance.service import jurnal_faktur_beli

    if jurnal_faktur_beli(db, organisation_id=organisation_id, user_id=user_id, invoice=invoice) is not None:
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
) -> PurchaseInvoice:
    """Bayar utang faktur (boleh sebagian) — membuat pembayaran + jurnalnya."""
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
        arah="keluar",
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
    from sqlalchemy import func

    def count_status(model, status: str) -> int:
        return db.execute(
            select(func.count())
            .select_from(model)
            .where(model.organisation_id == organisation_id, model.status == status)
        ).scalar_one()

    nilai_utang = db.execute(
        select(func.coalesce(func.sum(PurchaseInvoice.total), 0)).where(
            PurchaseInvoice.organisation_id == organisation_id, PurchaseInvoice.status == "unpaid"
        )
    ).scalar_one()
    from reptil.modules.finance.service import daftar_utang

    tagihan = daftar_utang(db, organisation_id)
    return {
        "po_draft": count_status(PurchaseOrder, "draft"),
        "po_received": count_status(PurchaseOrder, "received"),
        "invoice_unpaid": count_status(PurchaseInvoice, "unpaid") + count_status(PurchaseInvoice, "partial"),
        "nilai_utang": sum((t["sisa"] for t in tagihan), Decimal("0")),
    }
