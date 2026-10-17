"""Manajemen database REPTIL.

Tiga kemampuan:

1. **Statistik & kesehatan data** — jumlah baris per tabel, rentang tanggal, plus
   pemeriksaan wajar (kas negatif, stok negatif, jurnal tak seimbang, persediaan
   buku vs fisik, faktur tanpa pengiriman, tunggakan > 90 hari).
2. **Reset data** — hapus data transaksi, transaksi + master, atau reset awal
   (sisakan pengguna, peran, pengaturan aplikasi, dan bagan akun). Selalu
   ``additive-free``: hanya menghapus, tidak pernah mengubah angka jurnal.
3. **Job latar belakang** — pembuatan data demo & penghapusan dijalankan di thread
   terpisah dengan progres tersimpan di tabel ``data_jobs`` sehingga halaman web
   bisa memantau tanpa menunggu request selesai.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from reptil.core.db import SessionLocal
from reptil.core.sysinfo import waktu_sekarang
from reptil.modules.database.generator import OpsiDemo, bangkitkan, perkiraan
from reptil.modules.database.models import DataJob
from reptil.modules.finance import service as fin
from reptil.modules.finance.models import (
    AKUN_MODAL,
    AKUN_PERSEDIAAN,
    Account,
    JournalEntry,
    JournalLine,
    Payment,
    PaymentAllocation,
)
from reptil.modules.inventory.models import StockMovement
from reptil.modules.logistics.models import (
    Carrier,
    Route,
    RouteStop,
    Shipment,
    ShipmentLine,
    ShipmentStatusHistory,
    Vehicle,
)
from reptil.modules.masterdata.models import Item, Partner, Warehouse
from reptil.modules.purchasing.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from reptil.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesOrder,
    SalesOrderLine,
)

log = logging.getLogger("reptil.database")

NOL = Decimal("0")


def _uang(nilai: object) -> Decimal:
    return Decimal(str(nilai or 0)).quantize(Decimal("0.01"))


MODE_HAPUS = ("transaksi", "master", "total")
LABEL_MODE = {
    "transaksi": "Hapus data transaksi",
    "master": "Hapus transaksi + data master",
    "total": "Reset awal (kosongkan semua data)",
}
KETERANGAN_MODE = {
    "transaksi": (
        "Menghapus dokumen (pesanan, faktur, pembayaran, jurnal, stok, pengiriman). "
        "Item, pelanggan, pemasok, gudang, armada, dan bagan akun tetap tersimpan."
    ),
    "master": (
        "Seperti mode transaksi, ditambah menghapus item, pelanggan/pemasok, gudang, "
        "armada, ekspedisi, dan bagan akun (bagan akun dibuat ulang otomatis)."
    ),
    "total": (
        "Mengembalikan aplikasi ke kondisi awal: seluruh data di atas dihapus. "
        "Pengguna, peran, organisasi, dan pengaturan aplikasi tetap ada."
    ),
}

SATU_BULAN = timedelta(days=30)


# --------------------------------------------------------------------- statistik
@dataclass(frozen=True)
class BarisStatistik:
    label: str
    model: type
    kolom: object | None = None


STATISTIK: tuple[BarisStatistik, ...] = (
    BarisStatistik("Pelanggan & pemasok", Partner),
    BarisStatistik("Item", Item),
    BarisStatistik("Gudang", Warehouse),
    BarisStatistik("Pesanan pembelian", PurchaseOrder, PurchaseOrder.tanggal),
    BarisStatistik("Faktur pembelian", PurchaseInvoice, PurchaseInvoice.tanggal),
    BarisStatistik("Pesanan penjualan", SalesOrder, SalesOrder.tanggal),
    BarisStatistik("Faktur penjualan", SalesInvoice, SalesInvoice.tanggal),
    BarisStatistik("Pembayaran", Payment, Payment.tanggal),
    BarisStatistik("Jurnal", JournalEntry, JournalEntry.tanggal),
    BarisStatistik("Pergerakan stok", StockMovement, StockMovement.created_at),
    BarisStatistik("Pengiriman", Shipment, Shipment.created_at),
    BarisStatistik("Rute pengiriman", Route, Route.tanggal),
)


def statistik(db: Session, organisation_id: uuid.UUID) -> list[dict]:
    """Jumlah baris + rentang tanggal tiap tabel (untuk halaman manajemen database)."""
    hasil = []
    for baris in STATISTIK:
        jumlah = int(
            db.execute(
                select(func.count())
                .select_from(baris.model)
                .where(baris.model.organisation_id == organisation_id)
            ).scalar_one()
        )
        dari = sampai = None
        if baris.kolom is not None and jumlah:
            dari, sampai = db.execute(
                select(func.min(baris.kolom), func.max(baris.kolom)).where(
                    baris.model.organisation_id == organisation_id
                )
            ).one()
        hasil.append({"label": baris.label, "jumlah": jumlah, "dari": dari, "sampai": sampai})
    return hasil


def _status(bahaya: bool, peringatan: bool = False) -> str:
    if bahaya:
        return "bahaya"
    return "peringatan" if peringatan else "ok"


def kesehatan(db: Session, organisation_id: uuid.UUID) -> list[dict]:
    """Pemeriksaan kewajaran data — dipakai untuk menilai hasil data demo."""
    hasil: list[dict] = []

    ringkas = fin.ringkasan(db, organisation_id)
    kas = ringkas["saldo_kas"]
    hasil.append(
        {
            "nama": "Saldo Kas & Bank",
            "status": _status(kas < 0, kas < Decimal("10000000")),
            "nilai": kas,
            "pesan": (
                "Kas negatif — perlu setoran modal atau buat ulang data demo."
                if kas < 0
                else "Kas positif, siap membiayai operasional."
            ),
        }
    )

    neraca = fin.saldo_akun(db, organisation_id)
    total_debit = sum((a["debit"] for a in neraca), NOL)
    total_kredit = sum((a["credit"] for a in neraca), NOL)
    selisih = total_debit - total_kredit
    hasil.append(
        {
            "nama": "Neraca saldo",
            "status": _status(selisih != 0),
            "nilai": selisih,
            "pesan": (
                "Total debit = total kredit."
                if selisih == 0
                else "Tidak seimbang — periksa jurnal."
            ),
        }
    )

    jumlah_akun = {a["akun"].kode: a["saldo"] for a in neraca}
    modal = jumlah_akun.get(AKUN_MODAL, NOL)
    hasil.append(
        {
            "nama": "Modal disetor",
            "status": _status(False, modal <= 0),
            "nilai": modal,
            "pesan": (
                "Modal pemilik sudah tercatat."
                if modal > 0
                else "Akun modal masih nol (belum ada saldo awal)."
            ),
        }
    )

    tak_seimbang = int(
        db.execute(
            select(func.count()).select_from(
                select(JournalEntry.id)
                .outerjoin(JournalLine, JournalLine.entry_id == JournalEntry.id)
                .where(JournalEntry.organisation_id == organisation_id)
                .group_by(JournalEntry.id)
                .having(
                    func.abs(
                        func.coalesce(func.sum(JournalLine.debit), 0)
                        - func.coalesce(func.sum(JournalLine.credit), 0)
                    )
                    > Decimal("0.005")
                )
                .subquery()
            )
        ).scalar_one()
    )
    hasil.append(
        {
            "nama": "Jurnal seimbang",
            "status": _status(tak_seimbang > 0),
            "nilai": tak_seimbang,
            "pesan": (
                "Semua jurnal debit = kredit."
                if tak_seimbang == 0
                else f"{tak_seimbang} jurnal tidak seimbang."
            ),
        }
    )

    stok_negatif = int(
        db.execute(
            select(func.count()).select_from(
                select(StockMovement.item_id)
                .where(StockMovement.organisation_id == organisation_id)
                .group_by(StockMovement.item_id, StockMovement.warehouse_id)
                .having(func.sum(StockMovement.qty) < 0)
                .subquery()
            )
        ).scalar_one()
    )
    hasil.append(
        {
            "nama": "Stok tidak negatif",
            "status": _status(stok_negatif > 0),
            "nilai": stok_negatif,
            "pesan": (
                "Tidak ada saldo stok negatif."
                if stok_negatif == 0
                else f"{stok_negatif} kombinasi item/gudang bersaldo negatif."
            ),
        }
    )

    nilai_stok = db.execute(
        select(func.coalesce(func.sum(StockMovement.qty * Item.harga_beli), 0))
        .join(Item, Item.id == StockMovement.item_id)
        .where(StockMovement.organisation_id == organisation_id)
    ).scalar_one()
    nilai_stok = _uang(nilai_stok)
    led_akun = jumlah_akun.get(AKUN_PERSEDIAAN, NOL)
    selisih_stok = led_akun - nilai_stok
    hasil.append(
        {
            "nama": "Persediaan buku = fisik",
            "status": _status(abs(selisih_stok) > Decimal("1000")),
            "nilai": selisih_stok,
            "pesan": (
                f"Nilai buku Rp {led_akun:,.2f} = nilai stok Rp {nilai_stok:,.2f}."
                if abs(selisih_stok) <= Decimal("1000")
                else f"Selisih Rp {selisih_stok:,.2f} antara buku besar dan nilai stok "
                "(stok awal belum dijurnal?)."
            ),
        }
    )

    tanpa_kirim = int(
        db.execute(
            select(func.count())
            .select_from(SalesInvoice)
            .join(SalesOrder, SalesOrder.id == SalesInvoice.order_id)
            .where(
                SalesInvoice.organisation_id == organisation_id,
                SalesInvoice.status != "cancelled",
                SalesOrder.delivered_at.is_(None),
            )
        ).scalar_one()
    )
    hasil.append(
        {
            "nama": "Faktur jual punya pengiriman",
            "status": _status(tanpa_kirim > 0),
            "nilai": tanpa_kirim,
            "pesan": (
                "Semua faktur penjualan berasal dari pesanan yang sudah dikirim."
                if tanpa_kirim == 0
                else f"{tanpa_kirim} faktur penjualan tanpa pengiriman."
            ),
        }
    )

    batas = date.today() - timedelta(days=180)
    telat = int(
        db.execute(
            select(func.count())
            .select_from(SalesInvoice)
            .where(
                SalesInvoice.organisation_id == organisation_id,
                SalesInvoice.status.in_(("unpaid", "partial")),
                SalesInvoice.jatuh_tempo.is_not(None),
                SalesInvoice.jatuh_tempo < batas,
            )
        ).scalar_one()
        + db.execute(
            select(func.count())
            .select_from(PurchaseInvoice)
            .where(
                PurchaseInvoice.organisation_id == organisation_id,
                PurchaseInvoice.status.in_(("unpaid", "partial")),
                PurchaseInvoice.jatuh_tempo.is_not(None),
                PurchaseInvoice.jatuh_tempo < batas,
            )
        ).scalar_one()
    )
    hasil.append(
        {
            "nama": "Tunggakan > 180 hari",
            "status": _status(False, telat > 0),
            "nilai": telat,
            "pesan": (
                "Tidak ada tunggakan lebih dari 180 hari."
                if telat == 0
                else f"{telat} faktur tertunggak lebih dari 180 hari — perlu ditindaklanjuti."
            ),
        }
    )

    hasil.append(
        {
            "nama": "Papan umur terisi",
            "status": _status(
                False,
                all(
                    nilai["jumlah"] == 0
                    for nilai in (
                        *ringkas["aging_piutang"].values(),
                        *ringkas["aging_utang"].values(),
                    )
                ),
            ),
            "nilai": sum(v["jumlah"] for v in ringkas["aging_piutang"].values()),
            "pesan": "Piutang/utang tersebar di beberapa kelompok umur."
            if any(
                v["jumlah"]
                for v in (*ringkas["aging_piutang"].values(), *ringkas["aging_utang"].values())
            )
            else "Belum ada piutang/utang terbuka.",
        }
    )
    return hasil


# ------------------------------------------------------------------------- hapus
@dataclass(frozen=True)
class BarisHapus:
    label: str
    model: type
    induk: type | None = None
    kolom: str | None = None


SKEMA_TRANSAKSI: tuple[BarisHapus, ...] = (
    BarisHapus("Titik rute", RouteStop, Route, "route_id"),
    BarisHapus("Rute pengiriman", Route),
    BarisHapus("Riwayat status pengiriman", ShipmentStatusHistory, Shipment, "shipment_id"),
    BarisHapus("Baris pengiriman", ShipmentLine, Shipment, "shipment_id"),
    BarisHapus("Pengiriman", Shipment),
    BarisHapus("Alokasi pembayaran", PaymentAllocation, Payment, "payment_id"),
    BarisHapus("Pembayaran", Payment),
    BarisHapus("Baris jurnal", JournalLine, JournalEntry, "entry_id"),
    BarisHapus("Jurnal", JournalEntry),
    BarisHapus("Baris faktur penjualan", SalesInvoiceLine, SalesInvoice, "invoice_id"),
    BarisHapus("Faktur penjualan", SalesInvoice),
    BarisHapus("Baris pesanan penjualan", SalesOrderLine, SalesOrder, "order_id"),
    BarisHapus("Pesanan penjualan", SalesOrder),
    BarisHapus("Baris faktur pembelian", PurchaseInvoiceLine, PurchaseInvoice, "invoice_id"),
    BarisHapus("Faktur pembelian", PurchaseInvoice),
    BarisHapus("Baris pesanan pembelian", PurchaseOrderLine, PurchaseOrder, "order_id"),
    BarisHapus("Pesanan pembelian", PurchaseOrder),
    BarisHapus("Pergerakan stok", StockMovement),
)

SKEMA_MASTER: tuple[BarisHapus, ...] = (
    BarisHapus("Pelanggan & pemasok", Partner),
    BarisHapus("Item", Item),
    BarisHapus("Gudang", Warehouse),
    BarisHapus("Armada", Vehicle),
    BarisHapus("Ekspedisi", Carrier),
    BarisHapus("Bagan akun", Account),
)


def _skema(mode: str) -> tuple[BarisHapus, ...]:
    mode = mode if mode in MODE_HAPUS else "transaksi"
    if mode == "transaksi":
        return SKEMA_TRANSAKSI
    return (*SKEMA_TRANSAKSI, *SKEMA_MASTER)


def _hitung(db: Session, organisation_id: uuid.UUID, baris: BarisHapus) -> int:
    if baris.induk is None:
        pernyataan = (
            select(func.count())
            .select_from(baris.model)
            .where(baris.model.organisation_id == organisation_id)
        )
    else:
        kolom = getattr(baris.model, baris.kolom)
        pernyataan = (
            select(func.count())
            .select_from(baris.model)
            .where(
                kolom.in_(
                    select(baris.induk.id).where(baris.induk.organisation_id == organisation_id)
                )
            )
        )
    return int(db.execute(pernyataan).scalar_one())


def ringkasan_hapus(db: Session, organisation_id: uuid.UUID, mode: str = "transaksi") -> dict:
    """Pratinjau: berapa baris yang akan terhapus pada tiap mode."""
    baris = [{"label": b.label, "jumlah": _hitung(db, organisation_id, b)} for b in _skema(mode)]
    return {
        "mode": mode,
        "label": LABEL_MODE.get(mode, LABEL_MODE["transaksi"]),
        "keterangan": KETERANGAN_MODE.get(mode, ""),
        "baris": baris,
        "total": sum(b["jumlah"] for b in baris),
    }


def _pastikan_dasar(db: Session, organisation_id: uuid.UUID) -> None:
    """Setelah penghapusan: bagan akun dibuat ulang + pastikan ada satu gudang."""
    fin.pastikan_coa(db, organisation_id)
    ada_gudang = int(
        db.execute(
            select(func.count())
            .select_from(Warehouse)
            .where(Warehouse.organisation_id == organisation_id)
        ).scalar_one()
    )
    if not ada_gudang:
        db.add(
            Warehouse(
                organisation_id=organisation_id,
                kode="GDG-01",
                nama="Gudang Utama",
                is_default=True,
            )
        )
    db.commit()


def hapus_data(db: Session, organisation_id: uuid.UUID, mode: str = "transaksi") -> dict:
    """Hapus data sesuai mode. Anak (baris/riwayat) ikut terhapus lewat ON DELETE CASCADE."""
    mode = mode if mode in MODE_HAPUS else "transaksi"
    baris_hapus = _skema(mode)
    dihapus: list[dict] = []
    for baris in baris_hapus:
        jumlah = _hitung(db, organisation_id, baris)
        if baris.induk is None:
            db.execute(delete(baris.model).where(baris.model.organisation_id == organisation_id))
        dihapus.append({"label": baris.label, "jumlah": jumlah})
    db.commit()
    _pastikan_dasar(db, organisation_id)
    return {
        "mode": mode,
        "label": LABEL_MODE[mode],
        "dihapus": dihapus,
        "total": sum(b["jumlah"] for b in dihapus),
        "dihapus_pada": waktu_sekarang().isoformat(),
    }


def _opsi_dari_parameter(parameter: dict) -> dict:
    return {
        "bulan": int(parameter.get("bulan", 60)),
        "per_bulan": int(parameter.get("per_bulan", 12)),
        "skala": Decimal(str(parameter.get("skala", "1"))),
        "seed": int(parameter.get("seed", 20261017)),
        "logistik": bool(parameter.get("logistik", True)),
    }


def perkiraan_demo(parameter: dict) -> dict:
    return perkiraan(OpsiDemo(**_opsi_dari_parameter(parameter)))


# --------------------------------------------------------------------------- job
def daftar_job(db: Session, organisation_id: uuid.UUID, batas: int = 15) -> list[DataJob]:
    return list(
        db.execute(
            select(DataJob)
            .where(DataJob.organisation_id == organisation_id)
            .order_by(DataJob.created_at.desc())
            .limit(batas)
        ).scalars()
    )


def get_job(db: Session, organisation_id: uuid.UUID, job_id: uuid.UUID) -> DataJob | None:
    return (
        db.execute(
            select(DataJob).where(DataJob.id == job_id, DataJob.organisation_id == organisation_id)
        )
        .scalars()
        .first()
    )


def job_berjalan(db: Session, organisation_id: uuid.UUID) -> DataJob | None:
    return (
        db.execute(
            select(DataJob)
            .where(
                DataJob.organisation_id == organisation_id,
                DataJob.status.in_(("menunggu", "berjalan")),
            )
            .order_by(DataJob.created_at.desc())
        )
        .scalars()
        .first()
    )


def mulai_job(
    *,
    organisation_id: uuid.UUID,
    jenis: str,
    parameter: dict,
    user_id: uuid.UUID | None = None,
) -> DataJob:
    """Buat baris job (commit dulu) lalu jalankan di thread latar belakang."""
    with SessionLocal() as db:
        batas = waktu_sekarang() - timedelta(hours=2)
        for lama in db.execute(
            select(DataJob).where(
                DataJob.organisation_id == organisation_id,
                DataJob.status.in_(("menunggu", "berjalan")),
            )
        ).scalars():
            if (lama.mulai_pada or lama.created_at) < batas:
                lama.status = "gagal"
                lama.tahap = "Terputus"
                lama.pesan = "Proses terputus (server berhenti saat job berjalan)."
                lama.selesai_pada = waktu_sekarang()
        job = DataJob(
            organisation_id=organisation_id,
            jenis=jenis,
            status="menunggu",
            tahap="Menunggu antrean",
            persen=0,
            parameter=parameter,
            created_by=user_id,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    threading.Thread(
        target=_jalankan_job, args=(job_id,), name=f"data-job-{job_id}", daemon=True
    ).start()
    with SessionLocal() as db:
        return db.get(DataJob, job_id)


def _lapor(db: Session, job: DataJob):
    def lapor(persen: int, tahap: str) -> None:
        job.persen = max(0, min(100, int(persen)))
        job.tahap = tahap[:150]
        db.commit()

    return lapor


def _jalankan_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(DataJob, job_id)
        if job is None:
            return
        job.status = "berjalan"
        job.mulai_pada = waktu_sekarang()
        job.tahap = "Memulai"
        job.persen = 1
        db.commit()
        try:
            if job.jenis == "demo":
                parameter = dict(job.parameter or {})
                dibersihkan = None
                if parameter.get("bersihkan", True):
                    _lapor(db, job)(2, "Menghapus data lama")
                    dibersihkan = hapus_data(
                        db, job.organisation_id, parameter.get("mode_hapus", "transaksi")
                    )
                opsi = OpsiDemo(**_opsi_dari_parameter(parameter))
                hasil_demo = bangkitkan(
                    db, organisation_id=job.organisation_id, opsi=opsi, lapor=_lapor(db, job)
                )
                job.hasil = {"demo": hasil_demo, "dibersihkan": dibersihkan}
                job.pesan = (
                    f"Data demo {hasil_demo.get('bulan', 0)} bulan dibuat: "
                    f"{hasil_demo.get('faktur_jual', 0)} faktur penjualan, "
                    f"{hasil_demo.get('faktur_beli', 0)} faktur pembelian, "
                    f"{hasil_demo.get('pembayaran', 0)} pembayaran."
                )
            else:
                job.hasil = hapus_data(
                    db, job.organisation_id, (job.parameter or {}).get("mode", "transaksi")
                )
                job.pesan = (
                    f"{job.hasil.get('total', 0)} baris data dihapus "
                    f"({job.hasil.get('label', '')})."
                )
            job.status = "selesai"
            job.tahap = "Selesai"
            job.persen = 100
        except Exception as exc:
            db.rollback()
            log.exception("Job data %s gagal", job_id)
            job = db.get(DataJob, job_id) or job
            job.status = "gagal"
            job.tahap = "Gagal"
            job.pesan = f"{type(exc).__name__}: {exc}"
        finally:
            job.selesai_pada = waktu_sekarang()
            db.commit()
