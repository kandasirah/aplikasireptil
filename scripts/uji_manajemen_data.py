#!/usr/bin/env python3
"""Uji modul Manajemen Database pada database uji (bukan produksi).

Contoh:
  DATABASE_URL=...aplikasireptil_uji .venv/bin/python scripts/uji_manajemen_data.py bersihkan
  DATABASE_URL=... .venv/bin/python scripts/uji_manajemen_data.py generate 60 12
  DATABASE_URL=... .venv/bin/python scripts/uji_manajemen_data.py laporan
"""

import sys
from datetime import date
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import func, select  # noqa: E402

from reptil.core.db import session_scope  # noqa: E402
from reptil.modules.database import service as svc  # noqa: E402
from reptil.modules.database.generator import OpsiDemo, bangkitkan  # noqa: E402
from reptil.modules.finance import service as fin  # noqa: E402
from reptil.modules.finance.models import (  # noqa: E402
    AKUN_HPP,
    AKUN_PENJUALAN,
    JournalEntry,
)
from reptil.modules.identity.models import Organisation  # noqa: E402
from reptil.modules.purchasing.models import PurchaseInvoice  # noqa: E402
from reptil.modules.sales.models import SalesInvoice  # noqa: E402

from reptil.modules.inventory import models as _m2  # noqa: E402,F401
from reptil.modules.logistics import models as _m6  # noqa: E402,F401
from reptil.modules.masterdata import models as _m1  # noqa: E402,F401
from reptil.modules.pengaturan import models as _m7  # noqa: E402,F401


def rp(nilai) -> str:
    return f"Rp {float(nilai or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _org(db):
    return db.execute(select(Organisation)).scalars().first()


def cmd_generate(bulan: int, per_bulan: int) -> None:
    with session_scope() as db:
        org = _org(db)
        mulai = time.time()
        hasil = bangkitkan(
            db,
            organisation_id=org.id,
            opsi=OpsiDemo(bulan=bulan, per_bulan=per_bulan),
            lapor=lambda persen, tahap: print(f"  [{persen:>3}%] {tahap}"),
        )
        print(f"SELESAI dalam {time.time() - mulai:.1f} detik")
        for kunci, nilai in hasil.items():
            print(f"  {kunci:>18}: {nilai}")


def cmd_bersihkan(mode: str) -> None:
    with session_scope() as db:
        org = _org(db)
        print("PRATINJAU:")
        for baris in svc.ringkasan_hapus(db, org.id, mode)["baris"]:
            if baris["jumlah"]:
                print(f"  {baris['label']:<32} {baris['jumlah']}")
        hasil = svc.hapus_data(db, org.id, mode)
        print(f"HAPUS ({hasil['label']}): {hasil['total']} baris")


def cmd_job(bulan: int, per_bulan: int) -> None:
    with session_scope() as db:
        org = _org(db)
        job = svc.mulai_job(
            organisation_id=org.id,
            jenis="demo",
            parameter={
                "bulan": bulan,
                "per_bulan": per_bulan,
                "skala": "1",
                "seed": 20261017,
                "logistik": True,
                "bersihkan": True,
                "mode_hapus": "transaksi",
            },
        )
        job_id = job.id
    terakhir = None
    for _ in range(600):
        time.sleep(1)
        with session_scope() as db:
            job = db.get(svc.DataJob, job_id)
            kunci = (job.persen, job.status)
            if kunci != terakhir:
                print(f"  [{job.persen:>3}%] {job.status} — {job.tahap}")
                terakhir = kunci
            if job.status in ("selesai", "gagal"):
                print("PESAN:", job.pesan)
                print("HASIL:", job.hasil)
                return


def cmd_laporan() -> None:
    with session_scope() as db:
        org = _org(db)
        print("== STATISTIK ==")
        for s in svc.statistik(db, org.id):
            print(f"  {s['label']:<26} {s['jumlah']:>7}  {s['dari']} → {s['sampai']}")
        print("== KESEHATAN ==")
        for k in svc.kesehatan(db, org.id):
            print(f"  {k['status']:<10} {k['nama']:<28} {k['nilai']} — {k['pesan']}")
        print("== AGING PIUTANG ==")
        for label, data in fin.aging(fin.daftar_piutang(db, org.id)).items():
            print(f"  {label:<18} {data['faktur']:>5} faktur  {rp(data['jumlah'])}")
        print("== AGING UTANG ==")
        for label, data in fin.aging(fin.daftar_utang(db, org.id)).items():
            print(f"  {label:<18} {data['faktur']:>5} faktur  {rp(data['jumlah'])}")
        print("== STATUS FAKTUR ==")
        for nama, model in (("jual", SalesInvoice), ("beli", PurchaseInvoice)):
            for status, jumlah, total in db.execute(
                select(model.status, func.count(), func.sum(model.total))
                .where(model.organisation_id == org.id)
                .group_by(model.status)
                .order_by(model.status)
            ):
                print(f"  faktur {nama:<5} {status:<9} {jumlah:>5}  {rp(total)}")
        print("== TAHUNAN (jurnal) ==")
        for tahun in range(2021, 2027):
            awal, akhir = date(tahun, 1, 1), date(tahun, 12, 31)
            penjualan = fin._kredit_akun(db, org.id, AKUN_PENJUALAN, awal, akhir)
            hpp = fin._debit_akun(db, org.id, AKUN_HPP, awal, akhir)
            if penjualan or hpp:
                print(f"  {tahun}: penjualan {rp(penjualan)} · HPP {rp(hpp)}")
        print("== NERACA SALDO (ringkas) ==")
        for a in fin.saldo_akun(db, org.id):
            if a["saldo"]:
                print(f"  {a['akun'].kode:<6} {a['akun'].nama:<22} {rp(a['saldo'])}")


def main() -> int:
    perintah = sys.argv[1] if len(sys.argv) > 1 else "laporan"
    if perintah == "generate":
        cmd_generate(int(sys.argv[2]), int(sys.argv[3]))
    elif perintah == "bersihkan":
        cmd_bersihkan(sys.argv[2] if len(sys.argv) > 2 else "transaksi")
    elif perintah == "job":
        cmd_job(int(sys.argv[2]), int(sys.argv[3]))
    else:
        cmd_laporan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
