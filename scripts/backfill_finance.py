#!/usr/bin/env python3
"""Siapkan data keuangan untuk faktur yang sudah ada (idempoten, aman diulang).

Yang dikerjakan per organisasi:

1. Membuat bagan akun bawaan bila belum ada.
2. Membuat jurnal otomatis untuk setiap faktur pembelian/penjualan yang belum
   dijurnal (satu dokumen = satu jurnal, dicek lewat `ref_type` + `ref_id`).
3. Menyelaraskan status faktur dengan alokasi pembayaran yang tercatat — faktur
   yang dulu "ditandai lunas" lewat tombol tanpa pembayaran akan kembali menjadi
   ``unpaid`` sehingga muncul di daftar utang/piutang.

Contoh:
  .venv/bin/python scripts/backfill_finance.py
  .venv/bin/python scripts/backfill_finance.py --org REPTIL
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

# Impor semua modul model agar relasi string (Partner, Item, …) terresolusi
from reptil.modules.finance import models as _finance_models  # noqa: E402, F401
from reptil.modules.identity import models as _identity_models  # noqa: E402, F401
from reptil.modules.identity.models import Organisation  # noqa: E402
from reptil.modules.inventory import models as _inventory_models  # noqa: E402, F401
from reptil.modules.logistics import models as _logistics_models  # noqa: E402, F401
from reptil.modules.masterdata import models as _masterdata_models  # noqa: E402, F401
from reptil.modules.pengaturan import models as _pengaturan_models  # noqa: E402, F401
from reptil.modules.purchasing import models as _purchasing_models  # noqa: E402, F401
from reptil.modules.sales import models as _sales_models  # noqa: E402, F401

from reptil.core.db import session_scope  # noqa: E402
from reptil.modules.finance.service import (  # noqa: E402
    NOL,
    backfill_jurnal,
    daftar_piutang,
    daftar_utang,
    pastikan_coa,
    sinkron_status_faktur,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill jurnal & status faktur REPTIL")
    parser.add_argument("--org", default="", help="batasi ke satu kode organisasi")
    args = parser.parse_args()

    with session_scope() as db:
        stmt = select(Organisation).order_by(Organisation.code)
        if args.org:
            stmt = stmt.where(Organisation.code == args.org.upper())
        organisations = list(db.execute(stmt).scalars())

        if not organisations:
            print("Tidak ada organisasi yang cocok.")
            return 1

        for org in organisations:
            print(f"Organisasi {org.code} — {org.name}")
            print(f"  bagan akun   : {len(pastikan_coa(db, org.id))} akun")
            dibuat = backfill_jurnal(db, org.id)
            print(
                f"  jurnal dibuat: {dibuat['beli']} faktur pembelian, {dibuat['jual']} faktur penjualan"
            )
            ubah = sinkron_status_faktur(db, org.id)
            print(f"  status diubah: {ubah}")
            utang = daftar_utang(db, org.id)
            piutang = daftar_piutang(db, org.id)
            total_utang = sum((b["sisa"] for b in utang), NOL)
            total_piutang = sum((b["sisa"] for b in piutang), NOL)
            print(f"  utang        : {total_utang:,.2f} ({len(utang)} faktur)")
            print(f"  piutang      : {total_piutang:,.2f} ({len(piutang)} faktur)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
