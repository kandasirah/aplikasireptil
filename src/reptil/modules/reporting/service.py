"""Service reporting REPTIL: penjualan per periode, laba-rugi, nilai stok, ekspor CSV/XLSX.

Semua laporan **membaca** dari sumber yang sudah ada (faktur, mutasi stok, jurnal) —
tidak ada angka yang disimpan ulang. Rentang tanggal bersifat inklusif; bila
dikosongkan, laporan memakai bulan berjalan.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reptil.core.sysinfo import waktu_sekarang
from reptil.modules.finance import service as fin
from reptil.modules.finance.models import Account, JournalEntry, JournalLine
from reptil.modules.inventory.models import StockMovement
from reptil.modules.masterdata.models import Item, Partner
from reptil.modules.purchasing.models import PurchaseInvoice
from reptil.modules.sales.models import SalesInvoice, SalesInvoiceLine

NOL = Decimal("0")
KODE_HPP = "5-100"  # akun Harga Pokok Penjualan pada bagan akun bawaan
KELOMPOK_PERIODE = ("hari", "bulan")
LABEL_KELOMPOK = {"hari": "Harian", "bulan": "Bulanan"}
_TRUNC = {"hari": "day", "bulan": "month"}

LABEL_MUTASI = {
    "purchase_receipt": "Penerimaan pembelian",
    "sales_delivery": "Pengiriman penjualan",
    "adjustment": "Penyesuaian",
    "opname": "Stok opname",
}
LABEL_STATUS_FAKTUR = {
    "unpaid": "Belum bayar",
    "partial": "Dibayar sebagian",
    "paid": "Lunas",
    "cancelled": "Batal",
}


def uang(nilai: object) -> Decimal:
    return Decimal(str(nilai or 0)).quantize(Decimal("0.01"))


def rentang_bulan_ini() -> tuple[date, date]:
    """Awal bulan berjalan s.d. hari ini — rentang default semua laporan."""
    hari_ini = date.today()
    return hari_ini.replace(day=1), hari_ini


def nama_file(kode: str, ekstensi: str, dari: date, sampai: date) -> str:
    return f"reptil-{kode}-{dari.isoformat()}_{sampai.isoformat()}.{ekstensi}"


# ------------------------------------------------------------------ laporan
def penjualan_per_periode(
    db: Session,
    organisation_id: uuid.UUID,
    dari: date,
    sampai: date,
    kelompok: str = "hari",
) -> list[dict]:
    """Total faktur penjualan (di luar yang dibatalkan) per hari atau per bulan."""
    if kelompok not in KELOMPOK_PERIODE:
        kelompok = "hari"
    kolom = func.date_trunc(_TRUNC[kelompok], SalesInvoice.tanggal)
    stmt = (
        select(
            kolom.label("periode"),
            func.count().label("jumlah"),
            func.coalesce(func.sum(SalesInvoice.total), 0).label("total"),
        )
        .where(
            SalesInvoice.organisation_id == organisation_id,
            SalesInvoice.status != "cancelled",
            SalesInvoice.tanggal >= dari,
            SalesInvoice.tanggal <= sampai,
        )
        .group_by(kolom)
        .order_by(kolom)
    )
    baris = []
    for periode, jumlah, total in db.execute(stmt):
        tanggal = periode.date() if isinstance(periode, datetime) else periode
        label = tanggal.strftime("%Y-%m") if kelompok == "bulan" else tanggal.isoformat()
        baris.append({"periode": label, "jumlah": int(jumlah), "total": uang(total)})
    return baris


def penjualan_per_item(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date, batas: int = 25
) -> list[dict]:
    stmt = (
        select(
            Item.sku,
            Item.nama,
            Item.satuan,
            func.coalesce(func.sum(SalesInvoiceLine.qty), 0).label("qty"),
            func.coalesce(func.sum(SalesInvoiceLine.subtotal), 0).label("total"),
        )
        .join(SalesInvoiceLine, SalesInvoiceLine.item_id == Item.id)
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoice.organisation_id == organisation_id,
            SalesInvoice.status != "cancelled",
            SalesInvoice.tanggal >= dari,
            SalesInvoice.tanggal <= sampai,
        )
        .group_by(Item.sku, Item.nama, Item.satuan)
        .order_by(func.coalesce(func.sum(SalesInvoiceLine.subtotal), 0).desc())
        .limit(batas)
    )
    return [
        {
            "sku": r.sku,
            "nama": r.nama,
            "satuan": r.satuan,
            "qty": Decimal(r.qty),
            "total": uang(r.total),
        }
        for r in db.execute(stmt)
    ]


def penjualan_per_pelanggan(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date, batas: int = 25
) -> list[dict]:
    stmt = (
        select(
            Partner.kode,
            Partner.nama,
            func.count().label("jumlah"),
            func.coalesce(func.sum(SalesInvoice.total), 0).label("total"),
        )
        .join(SalesInvoice, SalesInvoice.customer_id == Partner.id)
        .where(
            SalesInvoice.organisation_id == organisation_id,
            SalesInvoice.status != "cancelled",
            SalesInvoice.tanggal >= dari,
            SalesInvoice.tanggal <= sampai,
        )
        .group_by(Partner.kode, Partner.nama)
        .order_by(func.coalesce(func.sum(SalesInvoice.total), 0).desc())
        .limit(batas)
    )
    return [
        {"kode": r.kode, "nama": r.nama, "jumlah": int(r.jumlah), "total": uang(r.total)}
        for r in db.execute(stmt)
    ]


def laba_rugi(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> dict:
    """Pendapatan & beban dari jurnal (hanya entri berstatus posted)."""
    stmt = (
        select(
            Account,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            Account.organisation_id == organisation_id,
            Account.tipe.in_(("revenue", "expense")),
            JournalEntry.status == "posted",
            JournalEntry.tanggal >= dari,
            JournalEntry.tanggal <= sampai,
        )
        .group_by(Account.id)
        .order_by(Account.kode)
    )
    pendapatan: list[dict] = []
    beban: list[dict] = []
    for akun, debit, credit in db.execute(stmt):
        debit, credit = uang(debit), uang(credit)
        nilai = (credit - debit) if akun.tipe == "revenue" else (debit - credit)
        (pendapatan if akun.tipe == "revenue" else beban).append({"akun": akun, "nilai": nilai})

    total_pendapatan = sum((b["nilai"] for b in pendapatan), NOL)
    total_beban = sum((b["nilai"] for b in beban), NOL)
    return {
        "pendapatan": pendapatan,
        "beban": beban,
        "total_pendapatan": total_pendapatan,
        "total_beban": total_beban,
        "laba": total_pendapatan - total_beban,
    }


def hpp_periode(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> Decimal:
    """Harga pokok penjualan periode ini.

    Diambil dari akun HPP di jurnal (buku besar = sumber kebenaran) supaya angka
    laporan tidak pernah berselisih dengan neraca saldo. Bila akun HPP belum ada
    (mis. COA diubah pengguna), dihitung cadangan: qty terjual × harga beli item.
    """
    akun_hpp = db.execute(
        select(Account.id).where(
            Account.organisation_id == organisation_id, Account.kode == KODE_HPP
        )
    ).scalar_one_or_none()
    if akun_hpp is not None:
        stmt = (
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_id == akun_hpp,
                JournalEntry.status == "posted",
                JournalEntry.tanggal >= dari,
                JournalEntry.tanggal <= sampai,
            )
        )
        return uang(db.execute(stmt).scalar_one())

    stmt = (
        select(func.coalesce(func.sum(SalesInvoiceLine.qty * Item.harga_beli), 0))
        .join(Item, Item.id == SalesInvoiceLine.item_id)
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoice.organisation_id == organisation_id,
            SalesInvoice.status != "cancelled",
            SalesInvoice.tanggal >= dari,
            SalesInvoice.tanggal <= sampai,
        )
    )
    return uang(db.execute(stmt).scalar_one())


def nilai_stok(db: Session, organisation_id: uuid.UUID) -> dict:
    """Nilai persediaan per item: saldo × harga beli (dan potensi × harga jual)."""
    qty_item = (
        select(
            StockMovement.item_id.label("item_id"),
            func.coalesce(func.sum(StockMovement.qty), 0).label("qty"),
        )
        .where(StockMovement.organisation_id == organisation_id)
        .group_by(StockMovement.item_id)
        .subquery()
    )
    stmt = (
        select(Item, func.coalesce(qty_item.c.qty, 0))
        .outerjoin(qty_item, qty_item.c.item_id == Item.id)
        .where(Item.organisation_id == organisation_id)
        .order_by(Item.nama)
    )
    baris = []
    for item, qty in db.execute(stmt):
        qty = Decimal(qty)
        harga_beli, harga_jual = uang(item.harga_beli), uang(item.harga_jual)
        baris.append(
            {
                "item": item,
                "qty": qty,
                "harga_beli": harga_beli,
                "harga_jual": harga_jual,
                "nilai_beli": qty * harga_beli,
                "nilai_jual": qty * harga_jual,
                "di_bawah_minimum": qty <= Decimal(item.stok_minimum),
            }
        )
    return {
        "baris": baris,
        "total_nilai_beli": sum((b["nilai_beli"] for b in baris), NOL),
        "total_nilai_jual": sum((b["nilai_jual"] for b in baris), NOL),
        "total_item": len(baris),
        "item_minimum": sum(1 for b in baris if b["di_bawah_minimum"]),
    }


def rekap(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> dict:
    """Angka utama untuk halaman Laporan."""
    total_penjualan = uang(
        db.execute(
            select(func.coalesce(func.sum(SalesInvoice.total), 0)).where(
                SalesInvoice.organisation_id == organisation_id,
                SalesInvoice.status != "cancelled",
                SalesInvoice.tanggal >= dari,
                SalesInvoice.tanggal <= sampai,
            )
        ).scalar_one()
    )
    jumlah_faktur = int(
        db.execute(
            select(func.count()).where(
                SalesInvoice.organisation_id == organisation_id,
                SalesInvoice.status != "cancelled",
                SalesInvoice.tanggal >= dari,
                SalesInvoice.tanggal <= sampai,
            )
        ).scalar_one()
    )
    lr = laba_rugi(db, organisation_id, dari, sampai)
    persediaan = nilai_stok(db, organisation_id)
    utang = fin.daftar_utang(db, organisation_id)
    piutang = fin.daftar_piutang(db, organisation_id)
    return {
        "total_penjualan": total_penjualan,
        "jumlah_faktur": jumlah_faktur,
        "rata_rata_faktur": (total_penjualan / jumlah_faktur) if jumlah_faktur else NOL,
        "hpp": hpp_periode(db, organisation_id, dari, sampai),
        "total_pendapatan": lr["total_pendapatan"],
        "total_beban": lr["total_beban"],
        "laba_bersih": lr["laba"],
        "nilai_persediaan": persediaan["total_nilai_beli"],
        "item_minimum": persediaan["item_minimum"],
        "total_utang": sum((b["sisa"] for b in utang), NOL),
        "total_piutang": sum((b["sisa"] for b in piutang), NOL),
    }


# ------------------------------------------------------------------- ekspor
@dataclass(frozen=True)
class DefinisiEkspor:
    """Definisi satu jenis ekspor: kolom, format tiap kolom, dan pengambil datanya."""

    kode: str
    judul: str
    keterangan: str
    kolom: tuple[str, ...]
    format_kolom: tuple[str, ...]  # teks | uang | angka | tanggal | datetime
    ambil: Callable[[Session, uuid.UUID, date, date], list[list]]
    periode: bool = True  # False untuk laporan posisi (stok, neraca) yang tidak terikat tanggal


def _ekspor_stok(db: Session, organisation_id: uuid.UUID, _dari: date, _sampai: date) -> list[list]:
    return [
        [
            b["item"].sku,
            b["item"].nama,
            b["item"].satuan,
            b["qty"],
            b["harga_beli"],
            b["nilai_beli"],
            b["harga_jual"],
            b["nilai_jual"],
            "Ya" if b["di_bawah_minimum"] else "Tidak",
        ]
        for b in nilai_stok(db, organisation_id)["baris"]
    ]


def _ekspor_mutasi(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> list[list]:
    stmt = (
        select(StockMovement)
        .where(
            StockMovement.organisation_id == organisation_id,
            func.date(StockMovement.created_at) >= dari,
            func.date(StockMovement.created_at) <= sampai,
        )
        .order_by(StockMovement.created_at)
    )
    return [
        [
            m.created_at,
            m.item.sku,
            m.item.nama,
            m.warehouse.nama,
            m.qty,
            LABEL_MUTASI.get(m.ref_type, m.ref_type),
            m.ref_number,
            m.note,
        ]
        for m in db.execute(stmt).scalars()
    ]


def _baris_faktur(_db: Session, faktur: SalesInvoice | PurchaseInvoice, dibayar: Decimal) -> list:
    total = uang(faktur.total)
    return [
        faktur.number,
        faktur.tanggal,
        faktur.jatuh_tempo,
        faktur.supplier.nama if isinstance(faktur, PurchaseInvoice) else faktur.customer.nama,
        total,
        dibayar,
        total - dibayar,
        LABEL_STATUS_FAKTUR.get(faktur.status, faktur.status),
    ]


KOLOM_FAKTUR = ("Nomor", "Tanggal", "Jatuh Tempo", "Pihak", "Total", "Dibayar", "Sisa", "Status")
FORMAT_FAKTUR = ("teks", "tanggal", "tanggal", "teks", "uang", "uang", "uang", "teks")


def _ekspor_faktur_jual(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date
) -> list[list]:
    stmt = (
        select(SalesInvoice)
        .where(
            SalesInvoice.organisation_id == organisation_id,
            SalesInvoice.tanggal >= dari,
            SalesInvoice.tanggal <= sampai,
        )
        .order_by(SalesInvoice.tanggal, SalesInvoice.number)
    )
    return [
        _baris_faktur(db, f, uang(f.total) - fin.sisa_faktur(db, f))
        for f in db.execute(stmt).scalars()
    ]


def _ekspor_faktur_beli(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date
) -> list[list]:
    stmt = (
        select(PurchaseInvoice)
        .where(
            PurchaseInvoice.organisation_id == organisation_id,
            PurchaseInvoice.tanggal >= dari,
            PurchaseInvoice.tanggal <= sampai,
        )
        .order_by(PurchaseInvoice.tanggal, PurchaseInvoice.number)
    )
    return [
        _baris_faktur(db, f, uang(f.total) - fin.sisa_faktur(db, f))
        for f in db.execute(stmt).scalars()
    ]


KOLOM_TAGIHAN = (
    "Faktur",
    "Pihak",
    "Tanggal",
    "Jatuh Tempo",
    "Total",
    "Dibayar",
    "Sisa",
    "Umur (hari)",
    "Kelompok Umur",
)
FORMAT_TAGIHAN = ("teks", "teks", "tanggal", "tanggal", "uang", "uang", "uang", "angka", "teks")


def _baris_tagihan(daftar: list[dict]) -> list[list]:
    return [
        [
            b["faktur"].number,
            b["partner"].nama,
            b["faktur"].tanggal,
            b["jatuh_tempo"],
            b["total"],
            b["dibayar"],
            b["sisa"],
            b["umur"],
            fin.LABEL_UMUR[b["kelompok"]],
        ]
        for b in daftar
    ]


def _ekspor_utang(
    db: Session, organisation_id: uuid.UUID, _dari: date, _sampai: date
) -> list[list]:
    return _baris_tagihan(fin.daftar_utang(db, organisation_id))


def _ekspor_piutang(
    db: Session, organisation_id: uuid.UUID, _dari: date, _sampai: date
) -> list[list]:
    return _baris_tagihan(fin.daftar_piutang(db, organisation_id))


def _ekspor_jurnal(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> list[list]:
    stmt = (
        select(JournalEntry)
        .where(
            JournalEntry.organisation_id == organisation_id,
            JournalEntry.tanggal >= dari,
            JournalEntry.tanggal <= sampai,
        )
        .order_by(JournalEntry.tanggal, JournalEntry.number)
    )
    baris = []
    for entri in db.execute(stmt).scalars():
        for lin in entri.lines:
            baris.append(
                [
                    entri.number,
                    entri.tanggal,
                    fin.LABEL_SUMBER.get(entri.sumber, entri.sumber),
                    lin.account.kode,
                    lin.account.nama,
                    lin.memo,
                    lin.debit,
                    lin.credit,
                    entri.status,
                ]
            )
    return baris


def _ekspor_neraca(db: Session, organisation_id: uuid.UUID, dari: date, sampai: date) -> list[list]:
    return [
        [
            b["akun"].kode,
            b["akun"].nama,
            fin.LABEL_TIPE_AKUN[b["akun"].tipe],
            b["sisi"],
            b["debit"],
            b["credit"],
            b["saldo"],
        ]
        for b in fin.saldo_akun(db, organisation_id, dari=dari, sampai=sampai)
    ]


def _ekspor_laba_rugi(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date
) -> list[list]:
    lr = laba_rugi(db, organisation_id, dari, sampai)
    baris: list[list] = []
    for b in lr["pendapatan"]:
        baris.append(["Pendapatan", b["akun"].kode, b["akun"].nama, b["nilai"]])
    baris.append(["Pendapatan", "", "Total Pendapatan", lr["total_pendapatan"]])
    for b in lr["beban"]:
        baris.append(["Beban", b["akun"].kode, b["akun"].nama, b["nilai"]])
    baris.append(["Beban", "", "Total Beban", lr["total_beban"]])
    baris.append(["Hasil", "", "Laba / (Rugi) Bersih", lr["laba"]])
    return baris


def _ekspor_penjualan_item(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date
) -> list[list]:
    return [
        [b["sku"], b["nama"], b["satuan"], b["qty"], b["total"]]
        for b in penjualan_per_item(db, organisation_id, dari, sampai, batas=10_000)
    ]


def _ekspor_penjualan_periode(
    db: Session, organisation_id: uuid.UUID, dari: date, sampai: date
) -> list[list]:
    return [
        [b["periode"], b["jumlah"], b["total"]]
        for b in penjualan_per_periode(db, organisation_id, dari, sampai, "hari")
    ]


EKSPOR: dict[str, DefinisiEkspor] = {
    d.kode: d
    for d in (
        DefinisiEkspor(
            "stok",
            "Nilai Persediaan",
            "Saldo dan nilai stok per item (harga beli & jual)",
            (
                "SKU",
                "Item",
                "Satuan",
                "Saldo",
                "Harga Beli",
                "Nilai Beli",
                "Harga Jual",
                "Nilai Jual",
                "Di Bawah Minimum",
            ),
            ("teks", "teks", "teks", "angka", "uang", "uang", "uang", "uang", "teks"),
            _ekspor_stok,
            periode=False,
        ),
        DefinisiEkspor(
            "mutasi",
            "Mutasi Stok",
            "Kartu stok (append-only) pada rentang tanggal",
            ("Waktu", "SKU", "Item", "Gudang", "Qty", "Jenis", "Referensi", "Catatan"),
            ("datetime", "teks", "teks", "teks", "angka", "teks", "teks", "teks"),
            _ekspor_mutasi,
        ),
        DefinisiEkspor(
            "faktur-jual",
            "Faktur Penjualan",
            "Faktur penjualan beserta sisa tagihannya",
            KOLOM_FAKTUR,
            FORMAT_FAKTUR,
            _ekspor_faktur_jual,
        ),
        DefinisiEkspor(
            "faktur-beli",
            "Faktur Pembelian",
            "Faktur pembelian beserta sisa tagihannya",
            KOLOM_FAKTUR,
            FORMAT_FAKTUR,
            _ekspor_faktur_beli,
        ),
        DefinisiEkspor(
            "utang",
            "Utang Usaha (AP)",
            "Faktur pembelian yang belum lunas + umur",
            KOLOM_TAGIHAN,
            FORMAT_TAGIHAN,
            _ekspor_utang,
        ),
        DefinisiEkspor(
            "piutang",
            "Piutang Usaha (AR)",
            "Faktur penjualan yang belum tertagih + umur",
            KOLOM_TAGIHAN,
            FORMAT_TAGIHAN,
            _ekspor_piutang,
        ),
        DefinisiEkspor(
            "jurnal",
            "Jurnal Umum",
            "Baris debit/kredit per jurnal pada rentang tanggal",
            (
                "Nomor",
                "Tanggal",
                "Sumber",
                "Kode Akun",
                "Nama Akun",
                "Keterangan",
                "Debit",
                "Kredit",
                "Status",
            ),
            ("teks", "tanggal", "teks", "teks", "teks", "teks", "uang", "uang", "teks"),
            _ekspor_jurnal,
        ),
        DefinisiEkspor(
            "neraca",
            "Neraca Saldo",
            "Saldo per akun pada rentang tanggal",
            ("Kode", "Nama Akun", "Tipe", "Saldo Normal", "Debit", "Kredit", "Saldo"),
            ("teks", "teks", "teks", "teks", "uang", "uang", "uang"),
            _ekspor_neraca,
            periode=False,
        ),
        DefinisiEkspor(
            "laba-rugi",
            "Laba Rugi",
            "Pendapatan, beban, dan hasil pada rentang tanggal",
            ("Kelompok", "Kode", "Akun", "Nilai"),
            ("teks", "teks", "teks", "uang"),
            _ekspor_laba_rugi,
        ),
        DefinisiEkspor(
            "penjualan-harian",
            "Penjualan Harian",
            "Jumlah & nilai faktur penjualan per hari",
            ("Tanggal", "Jumlah Faktur", "Total"),
            ("tanggal", "angka", "uang"),
            _ekspor_penjualan_periode,
        ),
        DefinisiEkspor(
            "penjualan-item",
            "Penjualan per Item",
            "Qty & nilai penjualan per item",
            ("SKU", "Item", "Satuan", "Qty", "Total"),
            ("teks", "teks", "teks", "angka", "uang"),
            _ekspor_penjualan_item,
        ),
    )
}


def get_ekspor(kode: str) -> DefinisiEkspor:
    from reptil.core.errors import NotFoundError

    definisi = EKSPOR.get(kode)
    if definisi is None:
        raise NotFoundError(f"Jenis ekspor '{kode}' tidak dikenal.")
    return definisi


# --------------------------------------------------------- pembentuk berkas
def _angka_rapi(nilai: Decimal) -> str:
    """12.000 → '12', 2.500 → '2.5' (pemisah desimal titik, tanpa nol ekor)."""
    return f"{nilai.normalize():f}"


def _teks_csv(nilai: object, format_kolom: str = "teks") -> str:
    if nilai is None:
        return ""
    if format_kolom == "uang" and not isinstance(nilai, (date, datetime)):
        return f"{uang(nilai):.2f}"
    if format_kolom == "angka" and not isinstance(nilai, (date, datetime)):
        return _angka_rapi(Decimal(str(nilai)))
    if isinstance(nilai, datetime):
        return nilai.astimezone().strftime("%d/%m/%Y %H:%M")
    if isinstance(nilai, date):
        return nilai.strftime("%d/%m/%Y")
    if isinstance(nilai, Decimal):
        return _angka_rapi(nilai)
    return str(nilai)


def buat_csv(kolom: tuple[str, ...], baris: list[list], format_kolom: tuple[str, ...]) -> bytes:
    """CSV UTF-8 dengan BOM agar Excel membaca huruf beraksen dengan benar."""
    buf = io.StringIO()
    tulis = csv.writer(buf, lineterminator="\r\n")
    tulis.writerow(list(kolom))
    for b in baris:
        tulis.writerow(
            [
                _teks_csv(v, format_kolom[i] if i < len(format_kolom) else "teks")
                for i, v in enumerate(b)
            ]
        )
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


_FORMAT_ANGKA_XLSX = {
    "uang": "#,##0.00",
    "angka": "#,##0.###",
    "tanggal": "DD/MM/YYYY",
    "datetime": "DD/MM/YYYY HH:MM",
}


def _nilai_xlsx(nilai: object) -> object:
    if isinstance(nilai, Decimal):
        return float(nilai)
    if isinstance(nilai, datetime):
        return nilai.astimezone().replace(tzinfo=None)
    if nilai is None:
        return ""
    return nilai


def buat_xlsx(
    kolom: tuple[str, ...],
    baris: list[list],
    *,
    judul: str,
    keterangan: str,
    format_kolom: tuple[str, ...],
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = judul[:31]

    jumlah_kolom = len(kolom)
    ws.append([judul])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=jumlah_kolom)
    sel_judul = ws.cell(row=1, column=1)
    sel_judul.font = Font(bold=True, size=14)
    sel_judul.alignment = Alignment(horizontal="left")

    ws.append([keterangan])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=jumlah_kolom)
    ws.cell(row=2, column=1).font = Font(size=9, color="66756C")

    ws.append(list(kolom))
    kepala = PatternFill("solid", start_color="E3F0E8")
    for i in range(1, jumlah_kolom + 1):
        sel = ws.cell(row=3, column=i)
        sel.font = Font(bold=True)
        sel.fill = kepala
        sel.alignment = Alignment(vertical="center")

    for b in baris:
        ws.append([_nilai_xlsx(v) for v in b])

    for i, format_kolom_sel in enumerate(format_kolom, start=1):
        if format_kolom_sel not in _FORMAT_ANGKA_XLSX:
            continue
        for j in range(4, 4 + len(baris)):
            ws.cell(row=j, column=i).number_format = _FORMAT_ANGKA_XLSX[format_kolom_sel]

    # lebar kolom menyesuaikan isi (dibatasi agar tidak melebar berlebihan)
    for i, nama_kolom in enumerate(kolom, start=1):
        terlebar = len(str(nama_kolom))
        for b in baris[:200]:
            if i - 1 < len(b):
                terlebar = max(terlebar, len(_teks_csv(b[i - 1], format_kolom[i - 1])))
        ws.column_dimensions[get_column_letter(i)].width = min(max(terlebar + 3, 10), 44)

    ws.freeze_panes = "A4"

    aliran = io.BytesIO()
    wb.save(aliran)
    return aliran.getvalue()


def ekspor(
    db: Session, organisation_id: uuid.UUID, kode: str, dari: date, sampai: date, format: str
) -> tuple[bytes, str, str]:
    """Kembalikan (isi berkas, media type, nama berkas) untuk satu jenis ekspor."""
    definisi = get_ekspor(kode)
    stamp = waktu_sekarang().strftime("%d/%m/%Y %H:%M")
    if definisi.periode:
        baris = definisi.ambil(db, organisation_id, dari, sampai)
        rentang = f"Periode {dari.strftime('%d/%m/%Y')}–{sampai.strftime('%d/%m/%Y')} · "
    else:
        baris = definisi.ambil(db, organisation_id, dari, sampai)
        rentang = "Posisi terkini · "
    keterangan = f"{definisi.keterangan} · {rentang}Diekspor {stamp}"
    if format == "xlsx":
        isi = buat_xlsx(
            definisi.kolom,
            baris,
            judul=definisi.judul,
            keterangan=keterangan,
            format_kolom=definisi.format_kolom,
        )
        return (
            isi,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            nama_file(kode, "xlsx", dari, sampai),
        )
    if format != "csv":
        from reptil.core.errors import BusinessRuleError

        raise BusinessRuleError("Format ekspor harus 'csv' atau 'xlsx'.")
    return (
        buat_csv(definisi.kolom, baris, definisi.format_kolom),
        "text/csv; charset=utf-8",
        nama_file(kode, "csv", dari, sampai),
    )
