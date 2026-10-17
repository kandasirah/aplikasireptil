"""Service finance REPTIL: bagan akun, jurnal umum, pembayaran, aging AP/AR.

Prinsip:

* **Jurnal seimbang dipaksa di kode** — total debit harus sama dengan total kredit,
  kalau tidak service menolak (bukan sekadar mengandalkan disiplin pemanggil).
* **Sisa faktur dihitung dari alokasi pembayaran**, bukan dari kolom yang di-update,
  sehingga tidak ada nilai yang bisa hilang karena dua permintaan bersamaan.
* **Penjurnalan otomatis idempoten**: satu dokumen = satu jurnal (dicek lewat
  `ref_type` + `ref_id`), aman dipanggil ulang saat backfill data lama.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, nulls_last, or_, select
from sqlalchemy.orm import Session

from reptil.core.documents import next_number_safe
from reptil.core.errors import BusinessRuleError, ConflictError, NotFoundError
from reptil.core.parsing import to_date, to_decimal
from reptil.modules.finance.models import (
    ACCOUNT_TYPES,
    AKUN_HPP,
    AKUN_KAS,
    AKUN_PENJUALAN,
    AKUN_PERSEDIAAN,
    AKUN_PIUTANG,
    AKUN_UTANG,
    COA_BAWAAN,
    NORMAL_DEBIT,
    PAYMENT_DIRECTIONS,
    PAYMENT_METHODS,
    Account,
    JournalEntry,
    JournalLine,
    Payment,
    PaymentAllocation,
)
from reptil.modules.purchasing.models import PurchaseInvoice
from reptil.modules.sales.models import SalesInvoice

NOL = Decimal("0")
LABEL_ARAH = {"masuk": "Penerimaan", "keluar": "Pembayaran"}
PREFIX_ARAH = {"masuk": "TM", "keluar": "BY"}
LABEL_SUMBER = {
    "faktur_beli": "Faktur pembelian",
    "faktur_jual": "Faktur penjualan",
    "pembayaran": "Pembayaran",
    "manual": "Manual",
}
LABEL_TIPE_AKUN = {
    "asset": "Aset",
    "liability": "Kewajiban",
    "equity": "Modal",
    "revenue": "Pendapatan",
    "expense": "Beban",
}


def _uang(nilai: object) -> Decimal:
    return Decimal(str(nilai or 0)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- bagan akun
def pastikan_coa(db: Session, organisation_id: uuid.UUID) -> dict[str, Account]:
    """Pastikan bagan akun bawaan ada; kembalikan peta kode → akun."""
    ada = {
        a.kode: a
        for a in db.execute(
            select(Account).where(Account.organisation_id == organisation_id)
        ).scalars()
    }
    baru = False
    for kode, nama, tipe in COA_BAWAAN:
        if kode not in ada:
            akun = Account(organisation_id=organisation_id, kode=kode, nama=nama, tipe=tipe)
            db.add(akun)
            ada[kode] = akun
            baru = True
    if baru:
        db.flush()
    return ada


def _akun_wajib(db: Session, organisation_id: uuid.UUID, kode: str) -> Account:
    akun = db.execute(
        select(Account).where(
            Account.organisation_id == organisation_id, Account.kode == kode
        )
    ).scalar_one_or_none()
    if akun is None:
        akun = pastikan_coa(db, organisation_id).get(kode)
    if akun is None:  # pragma: no cover — COA bawaan selalu memuat kode ini
        raise ConflictError(f"Akun {kode} belum ada di bagan akun.")
    return akun


def list_accounts(db: Session, organisation_id: uuid.UUID, q: str = "", tipe: str = "") -> list[Account]:
    stmt: Select = select(Account).where(Account.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Account.kode.ilike(like), Account.nama.ilike(like)))
    if tipe:
        stmt = stmt.where(Account.tipe == tipe)
    return list(db.execute(stmt.order_by(Account.kode)).scalars().all())


def buat_akun(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    kode: str,
    nama: str,
    tipe: str,
) -> Account:
    kode = (kode or "").strip()
    nama = (nama or "").strip()
    if not kode:
        raise BusinessRuleError("Kode akun wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama akun wajib diisi.")
    if tipe not in ACCOUNT_TYPES:
        raise BusinessRuleError("Tipe akun tidak dikenal.")
    if db.execute(
        select(Account.id).where(Account.organisation_id == organisation_id, Account.kode == kode)
    ).first():
        raise ConflictError(f"Akun dengan kode {kode} sudah ada.")
    akun = Account(organisation_id=organisation_id, kode=kode, nama=nama, tipe=tipe)
    db.add(akun)
    db.commit()
    db.refresh(akun)
    return akun


def ubah_akun(db: Session, *, organisation_id: uuid.UUID, akun_id: uuid.UUID, nama: str, aktif: bool) -> Account:
    akun = get_akun(db, organisation_id, akun_id)
    nama = (nama or "").strip()
    if not nama:
        raise BusinessRuleError("Nama akun wajib diisi.")
    akun.nama = nama
    akun.aktif = aktif
    db.add(akun)
    db.commit()
    db.refresh(akun)
    return akun


def get_akun(db: Session, organisation_id: uuid.UUID, akun_id: uuid.UUID) -> Account:
    akun = db.execute(
        select(Account).where(Account.id == akun_id, Account.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if akun is None:
        raise NotFoundError("Akun tidak ditemukan.")
    return akun


def akun_kas(db: Session, organisation_id: uuid.UUID) -> list[Account]:
    """Akun yang bisa dipakai sebagai sumber/tujuan uang (Kas & Bank + akun aset lain)."""
    pastikan_coa(db, organisation_id)
    return list(
        db.execute(
            select(Account)
            .where(Account.organisation_id == organisation_id, Account.tipe == "asset", Account.aktif.is_(True))
            .order_by(Account.kode)
        ).scalars()
    )


def akun_kas_default(db: Session, organisation_id: uuid.UUID) -> Account:
    """Akun kas/bank bawaan (1-100) untuk aksi cepat 'Bayar'/'Terima'."""
    return _akun_wajib(db, organisation_id, AKUN_KAS)


# --------------------------------------------------------------------- jurnal
def _baris_jurnal(
    akun: Account,
    *,
    debit: Decimal = NOL,
    credit: Decimal = NOL,
    memo: str | None = None,
    partner_id: uuid.UUID | None = None,
) -> dict:
    return {
        "akun": akun,
        "debit": _uang(debit),
        "credit": _uang(credit),
        "memo": memo,
        "partner_id": partner_id,
    }


def buat_jurnal(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    tanggal: date,
    baris: list[dict],
    memo: str | None = None,
    sumber: str = "manual",
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Buat satu jurnal; menolak bila tidak seimbang atau ada baris kosong."""
    if len(baris) < 2:
        raise BusinessRuleError("Jurnal minimal terdiri dari dua baris (debit dan kredit).")

    total_debit = sum((b["debit"] for b in baris), NOL)
    total_kredit = sum((b["credit"] for b in baris), NOL)
    if total_debit != total_kredit:
        raise BusinessRuleError(
            f"Jurnal tidak seimbang: debit {total_debit} vs kredit {total_kredit}."
        )
    if total_debit <= 0:
        raise BusinessRuleError("Jurnal bernilai nol tidak dapat disimpan.")
    for b in baris:
        if b["debit"] < 0 or b["credit"] < 0:
            raise BusinessRuleError("Nilai debit/kredit tidak boleh negatif.")
        if b["debit"] > 0 and b["credit"] > 0:
            raise BusinessRuleError("Satu baris jurnal hanya boleh debit atau kredit.")

    entri = JournalEntry(
        organisation_id=organisation_id,
        number=next_number_safe(db, JournalEntry, organisation_id, "JU"),
        tanggal=tanggal,
        memo=(memo or "").strip() or None,
        sumber=sumber,
        ref_type=ref_type,
        ref_id=ref_id,
        status="posted",
        total=total_debit,
        created_by=user_id,
    )
    for i, b in enumerate(baris, start=1):
        entri.lines.append(
            JournalLine(
                line_no=i,
                account_id=b["akun"].id,
                partner_id=b.get("partner_id"),
                debit=b["debit"],
                credit=b["credit"],
                memo=(b.get("memo") or None),
            )
        )
    db.add(entri)
    # flush agar nomor jurnal berikutnya pada transaksi yang sama tidak bentrok
    db.flush()
    return entri


def sudah_dijurnal(db: Session, *, organisation_id: uuid.UUID, ref_type: str, ref_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(JournalEntry.id).where(
                JournalEntry.organisation_id == organisation_id,
                JournalEntry.ref_type == ref_type,
                JournalEntry.ref_id == ref_id,
                JournalEntry.status == "posted",
            )
        ).first()
        is not None
    )


def jurnal_faktur_beli(
    db: Session, *, organisation_id: uuid.UUID, user_id: uuid.UUID | None, invoice: PurchaseInvoice
) -> JournalEntry | None:
    """Dr Persediaan / Cr Utang Usaha — dijalankan sekali per faktur."""
    if sudah_dijurnal(db, organisation_id=organisation_id, ref_type="purchase_invoice", ref_id=invoice.id):
        return None
    total = _uang(invoice.total)
    if total <= 0:
        return None
    entri = buat_jurnal(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        tanggal=invoice.tanggal,
        memo=f"Faktur pembelian {invoice.number} — {invoice.supplier.nama}",
        sumber="faktur_beli",
        ref_type="purchase_invoice",
        ref_id=invoice.id,
        baris=[
            _baris_jurnal(_akun_wajib(db, organisation_id, AKUN_PERSEDIAAN), debit=total, memo="Barang masuk"),
            _baris_jurnal(
                _akun_wajib(db, organisation_id, AKUN_UTANG),
                credit=total,
                memo=invoice.number,
                partner_id=invoice.supplier_id,
            ),
        ],
    )
    return entri


def jurnal_faktur_jual(
    db: Session, *, organisation_id: uuid.UUID, user_id: uuid.UUID | None, invoice: SalesInvoice
) -> JournalEntry | None:
    """Dr Piutang / Cr Penjualan (+ Dr HPP / Cr Persediaan bila harga beli diketahui)."""
    if sudah_dijurnal(db, organisation_id=organisation_id, ref_type="sales_invoice", ref_id=invoice.id):
        return None
    total = _uang(invoice.total)
    if total <= 0:
        return None

    baris = [
        _baris_jurnal(
            _akun_wajib(db, organisation_id, AKUN_PIUTANG),
            debit=total,
            memo=invoice.number,
            partner_id=invoice.customer_id,
        ),
        _baris_jurnal(_akun_wajib(db, organisation_id, AKUN_PENJUALAN), credit=total, memo="Penjualan"),
    ]

    # Harga pokok penjualan: qty × harga beli item saat ini (barang jasa → dilewati)
    hpp = _uang(
        sum(
            (Decimal(str(l.qty)) * Decimal(str(l.item.harga_beli or 0)) for l in invoice.lines),
            NOL,
        )
    )
    if hpp > 0:
        baris.append(
            _baris_jurnal(_akun_wajib(db, organisation_id, AKUN_HPP), debit=hpp, memo="Harga pokok")
        )
        baris.append(
            _baris_jurnal(_akun_wajib(db, organisation_id, AKUN_PERSEDIAAN), credit=hpp, memo="Barang keluar")
        )

    return buat_jurnal(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        tanggal=invoice.tanggal,
        memo=f"Faktur penjualan {invoice.number} — {invoice.customer.nama}",
        sumber="faktur_jual",
        ref_type="sales_invoice",
        ref_id=invoice.id,
        baris=baris,
    )


def backfill_jurnal(db: Session, organisation_id: uuid.UUID, user_id: uuid.UUID | None = None) -> dict[str, int]:
    """Buat jurnal untuk faktur lama yang belum dijurnal (idempoten)."""
    pastikan_coa(db, organisation_id)
    dibuat = {"beli": 0, "jual": 0}
    faktur_beli = db.execute(
        select(PurchaseInvoice).where(
            PurchaseInvoice.organisation_id == organisation_id,
            PurchaseInvoice.status != "cancelled",
        )
    ).scalars()
    for inv in faktur_beli:
        if jurnal_faktur_beli(db, organisation_id=organisation_id, user_id=user_id, invoice=inv) is not None:
            dibuat["beli"] += 1

    faktur_jual = db.execute(
        select(SalesInvoice).where(
            SalesInvoice.organisation_id == organisation_id, SalesInvoice.status != "cancelled"
        )
    ).scalars()
    for inv in faktur_jual:
        if jurnal_faktur_jual(db, organisation_id=organisation_id, user_id=user_id, invoice=inv) is not None:
            dibuat["jual"] += 1

    db.commit()
    return dibuat


def sinkron_status_faktur(db: Session, organisation_id: uuid.UUID) -> dict[str, int]:
    """Selaraskan status faktur dengan alokasi pembayaran yang tercatat.

    Dipakai sekali untuk data lama: faktur yang dulu "ditandai lunas" lewat tombol
    tanpa pembayaran akan kembali menjadi ``unpaid`` sehingga muncul di daftar
    utang/piutang — angka buku jadi konsisten dengan jurnal.
    """
    hasil = {"unpaid": 0, "partial": 0, "paid": 0}
    for model in (PurchaseInvoice, SalesInvoice):
        for faktur in db.execute(
            select(model).where(model.organisation_id == organisation_id, model.status != "cancelled")
        ).scalars():
            sebelum = faktur.status
            _perbarui_status_faktur(db, faktur)
            if faktur.status != sebelum:
                hasil[faktur.status] = hasil.get(faktur.status, 0) + 1
    db.commit()
    return hasil


def list_jurnal(
    db: Session,
    organisation_id: uuid.UUID,
    *,
    q: str = "",
    sumber: str = "",
    dari: date | None = None,
    sampai: date | None = None,
    batas: int = 200,
) -> list[JournalEntry]:
    stmt = select(JournalEntry).where(JournalEntry.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(JournalEntry.number.ilike(like), JournalEntry.memo.ilike(like)))
    if sumber:
        stmt = stmt.where(JournalEntry.sumber == sumber)
    if dari:
        stmt = stmt.where(JournalEntry.tanggal >= dari)
    if sampai:
        stmt = stmt.where(JournalEntry.tanggal <= sampai)
    return list(db.execute(stmt.order_by(JournalEntry.tanggal.desc(), JournalEntry.number.desc()).limit(batas)).scalars())


def get_jurnal(db: Session, organisation_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
    entri = db.execute(
        select(JournalEntry).where(
            JournalEntry.id == entry_id, JournalEntry.organisation_id == organisation_id
        )
    ).scalar_one_or_none()
    if entri is None:
        raise NotFoundError("Jurnal tidak ditemukan.")
    return entri


def saldo_akun(
    db: Session,
    organisation_id: uuid.UUID,
    *,
    dari: date | None = None,
    sampai: date | None = None,
) -> list[dict]:
    """Neraca saldo: total debit/kredit/saldo per akun (jurnal 'posted' saja)."""
    stmt = (
        select(
            Account,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(Account.organisation_id == organisation_id, JournalEntry.status == "posted")
        .group_by(Account.id)
        .order_by(Account.kode)
    )
    if dari:
        stmt = stmt.where(JournalEntry.tanggal >= dari)
    if sampai:
        stmt = stmt.where(JournalEntry.tanggal <= sampai)

    hasil = []
    for akun, debit, credit in db.execute(stmt):
        debit, credit = _uang(debit), _uang(credit)
        saldo = debit - credit if akun.tipe in NORMAL_DEBIT else credit - debit
        hasil.append(
            {"akun": akun, "debit": debit, "credit": credit, "saldo": saldo, "sisi": akun.saldo_normal}
        )
    return hasil


# ---------------------------------------------------------------- pembayaran
def _subquery_alokasi(kolom_faktur):
    return (
        select(
            kolom_faktur.label("faktur_id"),
            func.coalesce(func.sum(PaymentAllocation.jumlah), 0).label("dibayar"),
        )
        .group_by(kolom_faktur)
        .subquery()
    )


def sisa_faktur(db: Session, faktur: PurchaseInvoice | SalesInvoice) -> Decimal:
    """Sisa yang belum dibayar = total − jumlah alokasi pembayaran."""
    kolom = (
        PaymentAllocation.purchase_invoice_id
        if isinstance(faktur, PurchaseInvoice)
        else PaymentAllocation.sales_invoice_id
    )
    dibayar = db.execute(
        select(func.coalesce(func.sum(PaymentAllocation.jumlah), 0)).where(kolom == faktur.id)
    ).scalar_one()
    return _uang(faktur.total) - _uang(dibayar)


def _daftar_tagihan(
    db: Session,
    organisation_id: uuid.UUID,
    model,
    kolom_faktur,
    partner_attr: str,
) -> list[dict]:
    """Daftar faktur belum lunas + sisa + umur, diurutkan dari yang paling jatuh tempo."""
    alok = _subquery_alokasi(kolom_faktur)
    stmt = (
        select(model, func.coalesce(alok.c.dibayar, 0))
        .outerjoin(alok, alok.c.faktur_id == model.id)
        .where(model.organisation_id == organisation_id, model.status != "cancelled")
        .order_by(nulls_last(model.jatuh_tempo), model.tanggal)
    )
    hari_ini = date.today()
    hasil = []
    for faktur, dibayar in db.execute(stmt):
        total = _uang(faktur.total)
        dibayar = _uang(dibayar)
        sisa = total - dibayar
        if sisa <= 0:
            continue
        jatuh = faktur.jatuh_tempo or faktur.tanggal
        umur = (hari_ini - jatuh).days
        hasil.append(
            {
                "faktur": faktur,
                "partner": getattr(faktur, partner_attr),
                "total": total,
                "dibayar": dibayar,
                "sisa": sisa,
                "jatuh_tempo": faktur.jatuh_tempo,
                "umur": umur,
                "kelompok": kelompok_umur(umur),
            }
        )
    return hasil


def kelompok_umur(umur: int) -> str:
    """Kelompok umur tagihan (hari lewat jatuh tempo)."""
    if umur <= 0:
        return "belum_jatuh_tempo"
    if umur <= 30:
        return "1_30"
    if umur <= 60:
        return "31_60"
    if umur <= 90:
        return "61_90"
    return "lebih_90"


LABEL_UMUR = {
    "belum_jatuh_tempo": "Belum jatuh tempo",
    "1_30": "1–30 hari",
    "31_60": "31–60 hari",
    "61_90": "61–90 hari",
    "lebih_90": "> 90 hari",
}


def daftar_utang(db: Session, organisation_id: uuid.UUID) -> list[dict]:
    return _daftar_tagihan(db, organisation_id, PurchaseInvoice, PaymentAllocation.purchase_invoice_id, "supplier")


def daftar_piutang(db: Session, organisation_id: uuid.UUID) -> list[dict]:
    return _daftar_tagihan(db, organisation_id, SalesInvoice, PaymentAllocation.sales_invoice_id, "customer")


def aging(tagihan: list[dict]) -> dict[str, dict]:
    """Ringkas nilai tagihan per kelompok umur."""
    ringkas = {kunci: {"jumlah": NOL, "faktur": 0} for kunci in LABEL_UMUR}
    for baris in tagihan:
        sel = ringkas[baris["kelompok"]]
        sel["jumlah"] += baris["sisa"]
        sel["faktur"] += 1
    return ringkas


def _perbarui_status_faktur(db: Session, faktur: PurchaseInvoice | SalesInvoice) -> None:
    """Status mengikuti sisa: lunas / sebagian / belum dibayar."""
    if faktur.status == "cancelled":
        return
    sisa = sisa_faktur(db, faktur)
    total = _uang(faktur.total)
    if sisa <= 0:
        faktur.status = "paid"
        faktur.paid_at = faktur.paid_at or _sekarang()
    elif sisa < total:
        faktur.status = "partial"
        faktur.paid_at = None
    else:
        faktur.status = "unpaid"
        faktur.paid_at = None
    db.add(faktur)


def _sekarang():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def catat_pembayaran(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    arah: str,
    faktur_id: uuid.UUID,
    akun_id: uuid.UUID,
    jumlah: str | Decimal,
    tanggal: str | date,
    metode: str = "transfer",
    referensi: str | None = None,
    catatan: str | None = None,
) -> Payment:
    """Catat pembayaran/penerimaan satu faktur beserta jurnalnya.

    ``jumlah`` boleh sebagian (status faktur menjadi ``partial``); tidak boleh
    melebihi sisa tagihan.
    """
    if arah not in PAYMENT_DIRECTIONS:
        raise BusinessRuleError("Jenis pembayaran tidak dikenal.")
    if metode not in PAYMENT_METHODS:
        raise BusinessRuleError("Metode pembayaran tidak dikenal.")

    nilai = _uang(to_decimal(jumlah, "Jumlah pembayaran"))
    if nilai <= 0:
        raise BusinessRuleError("Jumlah pembayaran harus lebih dari nol.")

    if arah == "keluar":
        faktur = db.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.id == faktur_id, PurchaseInvoice.organisation_id == organisation_id
            )
        ).scalar_one_or_none()
        if faktur is None:
            raise NotFoundError("Faktur pembelian tidak ditemukan.")
        partner_id = faktur.supplier_id
        akun_lawan = _akun_wajib(db, organisation_id, AKUN_UTANG)
        partner = faktur.supplier.nama
        nomor_faktur = faktur.number
    else:
        faktur = db.execute(
            select(SalesInvoice).where(
                SalesInvoice.id == faktur_id, SalesInvoice.organisation_id == organisation_id
            )
        ).scalar_one_or_none()
        if faktur is None:
            raise NotFoundError("Faktur penjualan tidak ditemukan.")
        partner_id = faktur.customer_id
        akun_lawan = _akun_wajib(db, organisation_id, AKUN_PIUTANG)
        partner = faktur.customer.nama
        nomor_faktur = faktur.number

    if faktur.status == "cancelled":
        raise BusinessRuleError(f"Faktur {nomor_faktur} dibatalkan.")

    sisa = sisa_faktur(db, faktur)
    if sisa <= 0:
        raise BusinessRuleError(f"Faktur {nomor_faktur} sudah lunas.")
    if nilai > sisa:
        raise BusinessRuleError(
            f"Jumlah {nilai:,.2f} melebihi sisa tagihan {nomor_faktur} ({sisa:,.2f})."
        )

    akun_kas_bank = get_akun(db, organisation_id, akun_id)
    if akun_kas_bank.tipe != "asset":
        raise BusinessRuleError("Akun kas/bank harus bertipe aset.")

    tanggal_bayar = to_date(tanggal, "Tanggal pembayaran")
    pembayaran = Payment(
        organisation_id=organisation_id,
        number=next_number_safe(db, Payment, organisation_id, PREFIX_ARAH[arah]),
        arah=arah,
        tanggal=tanggal_bayar,
        partner_id=partner_id,
        akun_id=akun_kas_bank.id,
        jumlah=nilai,
        metode=metode,
        referensi=(referensi or "").strip() or None,
        catatan=(catatan or "").strip() or None,
        created_by=user_id,
    )
    if arah == "keluar":
        pembayaran.allocations.append(PaymentAllocation(purchase_invoice_id=faktur.id, jumlah=nilai))
    else:
        pembayaran.allocations.append(PaymentAllocation(sales_invoice_id=faktur.id, jumlah=nilai))
    db.add(pembayaran)
    # flush dulu: id pembayaran harus ada sebelum dipakai sebagai ref_id jurnal
    db.flush()

    label = "Pembayaran" if arah == "keluar" else "Penerimaan"
    if arah == "keluar":
        baris = [
            _baris_jurnal(akun_lawan, debit=nilai, memo=nomor_faktur, partner_id=partner_id),
            _baris_jurnal(akun_kas_bank, credit=nilai, memo=f"{label} {partner}"),
        ]
    else:
        baris = [
            _baris_jurnal(akun_kas_bank, debit=nilai, memo=f"{label} {partner}"),
            _baris_jurnal(akun_lawan, credit=nilai, memo=nomor_faktur, partner_id=partner_id),
        ]
    buat_jurnal(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        tanggal=tanggal_bayar,
        memo=f"{label} {nomor_faktur} — {partner}",
        sumber="pembayaran",
        ref_type=("purchase_payment" if arah == "keluar" else "sales_payment"),
        ref_id=pembayaran.id,
        baris=baris,
    )

    db.flush()
    _perbarui_status_faktur(db, faktur)
    db.commit()
    db.refresh(pembayaran)
    return pembayaran


def hapus_pembayaran(db: Session, *, organisation_id: uuid.UUID, payment_id: uuid.UUID) -> None:
    """Batalkan pembayaran: jurnal dijadikan 'void' (jejak tetap ada), alokasi dihapus."""
    pembayaran = get_pembayaran(db, organisation_id, payment_id)
    db.execute(
        JournalEntry.__table__.update()
        .where(
            JournalEntry.organisation_id == organisation_id,
            JournalEntry.ref_id == pembayaran.id,
            JournalEntry.ref_type.in_(("purchase_payment", "sales_payment")),
        )
        .values(status="void")
    )
    faktur = None
    for alokasi in pembayaran.allocations:
        if alokasi.purchase_invoice_id:
            faktur = db.get(PurchaseInvoice, alokasi.purchase_invoice_id)
        elif alokasi.sales_invoice_id:
            faktur = db.get(SalesInvoice, alokasi.sales_invoice_id)
    db.delete(pembayaran)
    db.flush()
    if faktur is not None:
        _perbarui_status_faktur(db, faktur)
    db.commit()


def list_pembayaran(
    db: Session,
    organisation_id: uuid.UUID,
    *,
    arah: str = "",
    q: str = "",
    dari: date | None = None,
    sampai: date | None = None,
    batas: int = 200,
) -> list[Payment]:
    stmt = select(Payment).where(Payment.organisation_id == organisation_id)
    if arah:
        stmt = stmt.where(Payment.arah == arah)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Payment.number.ilike(like), Payment.referensi.ilike(like)))
    if dari:
        stmt = stmt.where(Payment.tanggal >= dari)
    if sampai:
        stmt = stmt.where(Payment.tanggal <= sampai)
    return list(
        db.execute(stmt.order_by(Payment.tanggal.desc(), Payment.number.desc()).limit(batas)).scalars()
    )


def get_pembayaran(db: Session, organisation_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
    pembayaran = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if pembayaran is None:
        raise NotFoundError("Pembayaran tidak ditemukan.")
    return pembayaran


def faktur_belum_lunas(db: Session, organisation_id: uuid.UUID, arah: str) -> list[dict]:
    """Faktur yang masih ada sisanya, untuk pilihan di form pembayaran."""
    return daftar_utang(db, organisation_id) if arah == "keluar" else daftar_piutang(db, organisation_id)


def pembayaran_faktur(db: Session, faktur: PurchaseInvoice | SalesInvoice) -> list[dict]:
    """Riwayat pembayaran/penerimaan untuk satu faktur (terbaru di bawah)."""
    kolom = (
        PaymentAllocation.purchase_invoice_id
        if isinstance(faktur, PurchaseInvoice)
        else PaymentAllocation.sales_invoice_id
    )
    stmt = (
        select(Payment, PaymentAllocation.jumlah)
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .where(kolom == faktur.id)
        .order_by(Payment.tanggal, Payment.number)
    )
    return [{"payment": p, "jumlah": _uang(j)} for p, j in db.execute(stmt)]


def faktur_untuk_pembayaran(db: Session, organisation_id: uuid.UUID, faktur_id: uuid.UUID, arah: str):
    model = PurchaseInvoice if arah == "keluar" else SalesInvoice
    faktur = db.execute(
        select(model).where(model.id == faktur_id, model.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if faktur is None:
        raise NotFoundError("Faktur tidak ditemukan.")
    return faktur


# ---------------------------------------------------------------- ringkasan
def ringkasan(db: Session, organisation_id: uuid.UUID) -> dict:
    """Angka ringkas untuk halaman Keuangan dan dashboard."""
    hari_ini = date.today()
    batas_tujuh = hari_ini + timedelta(days=7)
    utang = daftar_utang(db, organisation_id)
    piutang = daftar_piutang(db, organisation_id)

    def jatuh_tempo_terdekat(daftar: list[dict]) -> Decimal:
        return sum(
            (b["sisa"] for b in daftar if b["jatuh_tempo"] and hari_ini <= b["jatuh_tempo"] <= batas_tujuh),
            NOL,
        )

    awal_bulan = hari_ini.replace(day=1)
    penjualan = _kredit_akun(db, organisation_id, AKUN_PENJUALAN, awal_bulan, hari_ini)
    hpp = _debit_akun(db, organisation_id, AKUN_HPP, awal_bulan, hari_ini)
    pembayaran_terakhir = list_pembayaran(db, organisation_id, batas=5)

    return {
        "total_utang": sum((b["sisa"] for b in utang), NOL),
        "jumlah_faktur_utang": len(utang),
        "total_piutang": sum((b["sisa"] for b in piutang), NOL),
        "jumlah_faktur_piutang": len(piutang),
        "utang_jatuh_tempo": jatuh_tempo_terdekat(utang),
        "piutang_jatuh_tempo": jatuh_tempo_terdekat(piutang),
        "saldo_kas": _debit_akun(db, organisation_id, AKUN_KAS, None, None)
        - _kredit_akun(db, organisation_id, AKUN_KAS, None, None),
        "penjualan_bulan_ini": penjualan,
        "hpp_bulan_ini": hpp,
        "laba_kotor_bulan_ini": penjualan - hpp,
        "pembayaran_terakhir": pembayaran_terakhir,
        "aging_utang": aging(utang),
        "aging_piutang": aging(piutang),
    }


def _debit_akun(db, organisation_id, kode: str, dari: date | None, sampai: date | None) -> Decimal:
    return _mutasi_akun(db, organisation_id, kode, "debit", dari, sampai)


def _kredit_akun(db, organisation_id, kode: str, dari: date | None, sampai: date | None) -> Decimal:
    return _mutasi_akun(db, organisation_id, kode, "kredit", dari, sampai)


def _mutasi_akun(db, organisation_id, kode: str, sisi: str, dari: date | None, sampai: date | None) -> Decimal:
    kolom = JournalLine.debit if sisi == "debit" else JournalLine.credit
    stmt = (
        select(func.coalesce(func.sum(kolom), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(
            Account.organisation_id == organisation_id,
            Account.kode == kode,
            JournalEntry.status == "posted",
        )
    )
    if dari:
        stmt = stmt.where(JournalEntry.tanggal >= dari)
    if sampai:
        stmt = stmt.where(JournalEntry.tanggal <= sampai)
    return _uang(db.execute(stmt).scalar_one())
