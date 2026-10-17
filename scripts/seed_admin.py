#!/usr/bin/env python3
"""Seed data awal REPTIL: organisasi, role admin, user login, gudang, contoh master data.

Contoh:
  .venv/bin/python scripts/seed_admin.py
  .venv/bin/python scripts/seed_admin.py --email saya@corp.co.id --password Rahasia#2026 --org DEMO
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from reptil.core.db import session_scope  # noqa: E402
from reptil.core.security import hash_password  # noqa: E402
from reptil.modules.identity.models import Organisation, Role, User  # noqa: E402
from reptil.modules.masterdata.models import Item, Partner, Warehouse  # noqa: E402
from reptil.modules.pengaturan.models import AppSetting  # noqa: E402


def get_or_create_org(db, code: str, name: str) -> Organisation:
    org = db.execute(select(Organisation).where(Organisation.code == code)).scalar_one_or_none()
    if org is None:
        org = Organisation(code=code, name=name)
        db.add(org)
        db.flush()
    return org


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed admin & data demo REPTIL")
    parser.add_argument("--org", default="REPTIL", help="kode organisasi")
    parser.add_argument("--org-name", default="PT Reptil Nusantara", help="nama organisasi")
    parser.add_argument("--email", default="admin@reptil.co.id")
    parser.add_argument("--password", default="Admin#2026")
    parser.add_argument(
        "--keep-password",
        action="store_true",
        help="jangan sentuh password bila user sudah ada (untuk dijalankan ulang di database berisi data nyata)",
    )
    parser.add_argument("--nama", default="Administrator", dest="full_name")
    parser.add_argument("--with-demo", action="store_true", help="tambahkan contoh partner/item/gudang")
    args = parser.parse_args()

    with session_scope() as db:
        org = get_or_create_org(db, args.org.upper(), args.org_name)

        role = db.execute(
            select(Role).where(Role.organisation_id == org.id, Role.name == "admin")
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                organisation_id=org.id,
                name="admin",
                description="Akses penuh organisasi",
                permissions=["*"],
            )
            db.add(role)
            db.flush()

        email = args.email.strip().lower()
        user = db.execute(
            select(User).where(User.organisation_id == org.id, User.email == email)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                organisation_id=org.id,
                email=email,
                full_name=args.full_name,
                password_hash=hash_password(args.password),
                roles=[role],
            )
            db.add(user)
            action = "dibuat"
        else:
            if args.keep_password:
                user.full_name = args.full_name
                action = "diperbarui (password DIBIARKAN)"
            else:
                user.password_hash = hash_password(args.password)
                action = "diperbarui (password direset)"

        if db.execute(
            select(Warehouse).where(Warehouse.organisation_id == org.id)
        ).first() is None:
            db.add(Warehouse(organisation_id=org.id, kode="GDG-01", nama="Gudang Utama", is_default=True))

        # Profil aplikasi & perusahaan (tampil di sidebar, login, dan kop faktur)
        if db.execute(
            select(AppSetting).where(AppSetting.organisation_id == org.id)
        ).scalar_one_or_none() is None:
            db.add(
                AppSetting(
                    organisation_id=org.id,
                    app_name="REPTIL",
                    app_tagline="Reliable Systems. Connected Business.",
                    company_name=args.org_name,
                    company_address="Jl. Reptil Raya No. 1, Jakarta Selatan 12345",
                    company_phone="021-5550100",
                    company_email="keuangan@reptil.co.id",
                    company_npwp="01.234.567.8-901.000",
                    invoice_note="Pembayaran melalui transfer ke rekening BCA 1234567890 a/n PT Reptil Nusantara.",
                    invoice_terms="Barang yang sudah dibeli tidak dapat ditukar setelah 3 hari. "
                                  "Faktur ini sah tanpa tanda tangan basah.",
                )
            )

        # Bagan akun bawaan (dipakai jurnal otomatis & pembayaran)
        from reptil.modules.finance.service import pastikan_coa  # noqa: PLC0415

        jumlah_akun = len(pastikan_coa(db, org.id))

        if args.with_demo:
            if db.execute(select(Partner).where(Partner.organisation_id == org.id)).first() is None:
                db.add_all(
                    [
                        Partner(organisation_id=org.id, kode="C-001", nama="PT Mitra Retail", tipe="customer", telepon="021-5550101"),
                        Partner(organisation_id=org.id, kode="S-001", nama="CV Sumber Pakan", tipe="supplier", telepon="021-5550202"),
                        Partner(organisation_id=org.id, kode="B-001", nama="Toko Serba Reptil", tipe="both"),
                    ]
                )
            if db.execute(select(Item).where(Item.organisation_id == org.id)).first() is None:
                db.add_all(
                    [
                        Item(organisation_id=org.id, sku="RPT-001", nama="Kandang Kaca 60cm", satuan="pcs",
                             berat_kg=Decimal("8.500"), volume_m3=Decimal("0.120"),
                             harga_beli=Decimal("450000"), harga_jual=Decimal("650000"),
                             stok_minimum=Decimal("5")),
                        Item(organisation_id=org.id, sku="RPT-002", nama="Lampu UVB 10.0", satuan="pcs",
                             berat_kg=Decimal("0.300"), volume_m3=Decimal("0.002"),
                             harga_beli=Decimal("120000"), harga_jual=Decimal("185000"),
                             stok_minimum=Decimal("10")),
                        Item(organisation_id=org.id, sku="RPT-003", nama="Pakan Jangkrik Premium 1kg", satuan="pack",
                             berat_kg=Decimal("1.000"), volume_m3=Decimal("0.005"),
                             harga_beli=Decimal("35000"), harga_jual=Decimal("55000"),
                             stok_minimum=Decimal("20")),
                        Item(organisation_id=org.id, sku="RPT-004", nama="Jasa Konsultasi Setup Terrarium",
                             tipe="jasa", satuan="jam",
                             harga_beli=Decimal("0"), harga_jual=Decimal("250000")),
                    ]
                )

        db.flush()
        print("Seed selesai:")
        print(f"  organisasi : {org.code} — {org.name}")
        print(f"  user       : {user.email} ({action})")
        print(f"  role       : {role.name} permissions={role.permissions}")
        print(f"  bagan akun : {jumlah_akun} akun")
        print(f"  password   : {args.password if action != 'diperbarui (password DIBIARKAN)' else '(tidak diubah)'}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
