#!/usr/bin/env python3
"""Seed data demo REPTIL: peran RBAC, pengguna, master data, dan transaksi 5 tahun.

Yang dibuat:

1. **Peran** sesuai katalog izin (admin, manajer, penjualan, pembelian, gudang,
   logistik, keuangan).
2. **Pengguna** contoh (satu per peran) dengan kata sandi yang sama.
3. **Master data**: partner (pemasok & pelanggan), item, gudang, armada, ekspedisi.
4. **Stok awal** untuk seluruh item.
5. **Transaksi 5 tahun terakhir**: PO → penerimaan → faktur → pembayaran,
   SO → pengiriman (+surat jalan) → faktur → pembayaran, rute harian, jurnal.

Skrip idempoten untuk bagian peran/pengguna/master data. Data transaksi hanya
dibuat bila belum ada; gunakan ``--reset`` untuk menghapus lalu membuat ulang.

Contoh:
  .venv/bin/python scripts/seed_demo.py
  .venv/bin/python scripts/seed_demo.py --years 5 --reset
  .venv/bin/python scripts/seed_demo.py --org REPTIL --password 'Rahasia#2026'
"""

from __future__ import annotations

import argparse
import calendar
import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import func, select, text, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import reptil.core.documents as docs  # noqa: E402
from reptil.core.db import SessionLocal  # noqa: E402
from reptil.core.security import hash_password  # noqa: E402
from reptil.modules.identity.models import Organisation, Role, User  # noqa: E402
from reptil.modules.identity.permissions import WILDCARD  # noqa: E402
from reptil.modules.inventory.models import StockMovement  # noqa: E402
from reptil.modules.inventory.service import record_movement, stock_of  # noqa: E402
from reptil.modules.logistics.service import (  # noqa: E402
    add_stop,
    create_shipment_from_order,
    save_carrier,
    save_route,
    save_vehicle,
    update_status,
    update_stop_status,
)
from reptil.modules.masterdata.models import Item, Partner, Warehouse  # noqa: E402
from reptil.modules.purchasing.service import create_invoice_from_order as buat_faktur_beli  # noqa: E402
from reptil.modules.purchasing.service import create_order as buat_po  # noqa: E402
from reptil.modules.purchasing.service import pay_invoice as bayar_beli  # noqa: E402
from reptil.modules.purchasing.service import receive_order as terima_po  # noqa: E402
from reptil.modules.sales.service import create_invoice_from_order as buat_faktur_jual  # noqa: E402
from reptil.modules.sales.service import create_order as buat_so  # noqa: E402
from reptil.modules.sales.service import deliver_order as kirim_so  # noqa: E402
from reptil.modules.sales.service import pay_invoice as bayar_jual  # noqa: E402

# ---------------------------------------------------------------------------
# Penomoran dokumen mengikuti PREFIX-TAHUN-URUT. Agar data 5 tahun punya nomor
# per tahun (bukan semua tahun berjalan), kita titipkan tanggal ke helper
# `next_number` lewat patch kecil pada modul `reptil.core.documents`.
# ---------------------------------------------------------------------------


class _TanggalPaksa(date):
    """Subclass date yang `today()`-nya bisa dipaksa (hanya saat seeding)."""

    _paksa: date | None = None

    @classmethod
    def today(cls) -> date:
        return cls._paksa or date.today()


docs.date = _TanggalPaksa  # type: ignore[assignment]


def paksa_tanggal(d: date) -> None:
    _TanggalPaksa._paksa = d


# ---------------------------------------------------------------------------
# Definisi peran & pengguna
# ---------------------------------------------------------------------------
PERAN: dict[str, tuple[str, list[str]]] = {
    "admin": ("Akses penuh organisasi", [WILDCARD]),
    "manajer": (
        "Melihat seluruh modul (hanya baca)",
        [
            "masterdata.read", "purchasing.read", "sales.read", "inventory.read",
            "finance.read", "logistics.read", "settings.read", "users.read", "roles.read",
            "reports.read",
        ],
    ),
    "penjualan": (
        "Tim penjualan — kelola SO & faktur jual",
        ["masterdata.read", "inventory.read", "sales.read", "sales.write", "logistics.read", "reports.read"],
    ),
    "pembelian": (
        "Tim pembelian — kelola PO & faktur beli",
        ["masterdata.read", "inventory.read", "purchasing.read", "purchasing.write", "finance.read"],
    ),
    "gudang": (
        "Operator gudang — stok & master data",
        ["masterdata.read", "inventory.read", "inventory.write"],
    ),
    "logistik": (
        "Tim pengiriman — surat jalan & rute",
        ["masterdata.read", "inventory.read", "sales.read", "logistics.read", "logistics.write"],
    ),
    "keuangan": (
        "Tim keuangan — jurnal, utang-piutang & pembayaran",
        ["masterdata.read", "purchasing.read", "sales.read", "finance.read", "finance.write", "reports.read"],
    ),
}

PENGGUNA: list[tuple[str, str, list[str]]] = [
    ("admin@reptil.co.id", "Administrator", ["admin"]),
    ("manajer@reptil.co.id", "Budi Santoso (Manajer)", ["manajer"]),
    ("penjualan@reptil.co.id", "Siti Rahmawati (Penjualan)", ["penjualan"]),
    ("pembelian@reptil.co.id", "Andi Pratama (Pembelian)", ["pembelian"]),
    ("gudang@reptil.co.id", "Joko Susilo (Gudang)", ["gudang"]),
    ("logistik@reptil.co.id", "Rudi Hartono (Logistik)", ["logistik"]),
    ("keuangan@reptil.co.id", "Dewi Lestari (Keuangan)", ["keuangan"]),
]

PEMASOK = [
    ("S-001", "CV Sumber Pakan Sejahtera", "Jl. Raya Bogor KM 26, Jakarta Timur"),
    ("S-002", "PT Aneka Terrarium Indonesia", "Kawasan Industri Pulogadung, Jakarta"),
    ("S-003", "UD Cahaya Reptil Nusantara", "Jl. Diponegoro No. 88, Bandung"),
]
PELANGGAN = [
    ("C-001", "PT Mitra Retail Nusantara", "Jl. Sudirman No. 12, Jakarta Pusat"),
    ("C-002", "Toko Serba Reptil Jaya", "Jl. Malioboro No. 45, Yogyakarta"),
    ("C-003", "Reptile House Surabaya", "Jl. Tunjungan No. 7, Surabaya"),
    ("C-004", "CV Exotic Pets Bali", "Jl. Sunset Road No. 99, Denpasar"),
    ("C-005", "Reptil Corner Medan", "Jl. Gatot Subroto No. 210, Medan"),
    ("C-006", "Zoo & Pet Supply Semarang", "Jl. Pandanaran No. 33, Semarang"),
]
ITEM = [
    ("RPT-001", "Kandang Kaca 60cm", "pcs", 450000, 650000, "8.500", "0.120"),
    ("RPT-002", "Lampu UVB 10.0 26W", "pcs", 120000, 185000, "0.300", "0.002"),
    ("RPT-003", "Pakan Jangkrik Premium 1kg", "pack", 35000, 55000, "1.000", "0.005"),
    ("RPT-004", "Substrat Cocopeat 5L", "pack", 28000, 45000, "2.500", "0.008"),
    ("RPT-005", "Water Dish Keramik Besar", "pcs", 65000, 99000, "0.800", "0.003"),
    ("RPT-006", "Thermostat Digital Reptil", "pcs", 210000, 315000, "0.250", "0.002"),
    ("RPT-007", "Kandang Plastik XL", "pcs", 180000, 275000, "3.200", "0.045"),
    ("RPT-008", "Vitamin & Kalsium Reptil 100ml", "botol", 42000, 68000, "0.200", "0.001"),
    ("RPT-009", "Humidifier Mini Terrarium", "pcs", 165000, 245000, "0.900", "0.004"),
    ("RPT-010", "Pemanas Ceramic 60W", "pcs", 95000, 145000, "0.350", "0.002"),
]

ARMADA = [
    ("ARM-01", "Truk Box Engkel", "truk", "B 9021 RPT", 3000, 12, "Sugiyanto", "0812-1111-0001"),
    ("ARM-02", "Truk Box Double", "truk", "B 9022 RPT", 5000, 22, "Marno", "0812-1111-0002"),
    ("ARM-03", "Pickup L300", "pickup", "B 9023 RPT", 1500, 6, "Wahyu", "0812-1111-0003"),
    ("ARM-04", "Motor Roda Tiga", "motor", "B 9024 RPT", 300, 1, "Slamet", "0812-1111-0004"),
]
EKSPEDISI = [
    ("EXP-01", "JNE Trucking", "021-5550100", "https://www.jne.co.id/tracking"),
    ("EXP-02", "SiCepat Kargo", "021-5550200", "https://www.sicepat.com/track"),
    ("EXP-003", "Indah Kargo", "021-5550300", None),
]

TABEL_TRANSAKSI = [
    "payments", "journal_entries", "shipments", "routes",
    "sales_invoices", "purchase_invoices", "sales_orders", "purchase_orders",
    "stock_movements",
]


def _r2(nilai: Decimal) -> Decimal:
    return nilai.quantize(Decimal("0.01"))


def _dt(d: date, jam: int = 10, menit: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, jam, menit, tzinfo=UTC)


def _bulan_rentang(mulai: date, sampai: date):
    y, m = mulai.year, mulai.month
    while (y, m) <= (sampai.year, sampai.month):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


# --------------------------------------------------------------- reset data
def reset_transaksi(db: Session, org: Organisation) -> None:
    print("  • menghapus data transaksi lama…")
    for tabel in TABEL_TRANSAKSI:
        db.execute(text(f"DELETE FROM {tabel} WHERE organisation_id = :org"), {"org": org.id})
    db.commit()


# ------------------------------------------------------------ master data
def siapkan_peran(db: Session, org: Organisation) -> dict[str, Role]:
    hasil: dict[str, Role] = {}
    for nama, (deskripsi, izin) in PERAN.items():
        role = db.execute(
            select(Role).where(Role.organisation_id == org.id, Role.name == nama)
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                organisation_id=org.id, name=nama, description=deskripsi, permissions=izin
            )
            db.add(role)
            db.flush()
            print(f"  + peran {nama}")
        hasil[nama] = role
    db.commit()
    return hasil


def siapkan_pengguna(
    db: Session, org: Organisation, peran: dict[str, Role], password: str
) -> dict[str, User]:
    hasil: dict[str, User] = {}
    for email, nama_lengkap, daftar_peran in PENGGUNA:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(
                organisation_id=org.id,
                email=email,
                full_name=nama_lengkap,
                password_hash=hash_password(password),
                is_active=True,
                roles=[peran[p] for p in daftar_peran],
            )
            db.add(user)
            db.flush()
            print(f"  + pengguna {email}")
        else:
            user.full_name = nama_lengkap
            user.password_hash = hash_password(password)
            user.roles = [peran[p] for p in daftar_peran]
        hasil[email] = user
    db.commit()
    return hasil


def siapkan_master(db: Session, org: Organisation) -> dict:
    """Pastikan partner, item, gudang, armada, ekspedisi ada (upsert)."""
    def ada_partner(kode):
        return db.execute(
            select(Partner).where(Partner.organisation_id == org.id, Partner.kode == kode)
        ).scalar_one_or_none()

    for kode, nama, alamat in PEMASOK:
        p = ada_partner(kode)
        if p is None:
            p = Partner(organisation_id=org.id, kode=kode)
            db.add(p)
        p.nama, p.alamat, p.tipe, p.is_active = nama, alamat, "supplier", True
    for kode, nama, alamat in PELANGGAN:
        p = ada_partner(kode)
        if p is None:
            p = Partner(organisation_id=org.id, kode=kode)
            db.add(p)
        p.nama, p.alamat, p.tipe, p.is_active = nama, alamat, "customer", True
    db.commit()

    def ada_item(sku):
        return db.execute(
            select(Item).where(Item.organisation_id == org.id, Item.sku == sku)
        ).scalar_one_or_none()

    for sku, nama, satuan, beli, jual, berat, volume in ITEM:
        it = ada_item(sku)
        if it is None:
            it = Item(organisation_id=org.id, sku=sku)
            db.add(it)
        it.nama, it.satuan, it.tipe = nama, satuan, "produk"
        it.berat_kg = Decimal(berat)
        it.volume_m3 = Decimal(volume)
        it.harga_beli = Decimal(beli)
        it.harga_jual = Decimal(jual)
        it.stok_minimum = Decimal("10")
        it.is_active = True
    db.commit()

    def ada_gudang(kode):
        return db.execute(
            select(Warehouse).where(Warehouse.organisation_id == org.id, Warehouse.kode == kode)
        ).scalar_one_or_none()

    for kode, nama, alamat, default in [
        ("GDG-01", "Gudang Utama", "Jl. Reptil Raya No. 1, Jakarta Selatan", True),
        ("GDG-02", "Gudang Cabang Bandung", "Jl. Diponegoro No. 88, Bandung", False),
    ]:
        g = ada_gudang(kode)
        if g is None:
            g = Warehouse(organisation_id=org.id, kode=kode)
            db.add(g)
        g.nama, g.alamat, g.is_default, g.is_active = nama, alamat, default, True
    db.commit()

    from reptil.modules.logistics.models import Carrier, Vehicle  # noqa: PLC0415

    for kode, nama, tipe, plat, kap_kg, kap_m3, pengemudi, telepon in ARMADA:
        ada = db.execute(
            select(Vehicle).where(Vehicle.organisation_id == org.id, Vehicle.kode == kode)
        ).scalar_one_or_none()
        save_vehicle(
            db, org.id,
            {
                "kode": kode, "nama": nama, "tipe": tipe, "plat": plat,
                "kapasitas_kg": str(kap_kg), "kapasitas_m3": str(kap_m3),
                "pengemudi": pengemudi, "telepon_pengemudi": telepon,
                "status": "tersedia", "is_active": True,
            },
            ada.id if ada else None,
        )
    for kode, nama, telepon, url in EKSPEDISI:
        ada = db.execute(
            select(Carrier).where(Carrier.organisation_id == org.id, Carrier.kode == kode)
        ).scalar_one_or_none()
        save_carrier(
            db, org.id,
            {"kode": kode, "nama": nama, "telepon": telepon, "tracking_url": url, "is_active": True},
            ada.id if ada else None,
        )

    db.commit()
    return {"items": list(db.execute(select(Item).where(Item.organisation_id == org.id)).scalars()),
            "gudang": list(db.execute(select(Warehouse).where(Warehouse.organisation_id == org.id)).scalars()),
            "armada": list(db.execute(select(Vehicle).where(Vehicle.organisation_id == org.id)).scalars()),
            "ekspedisi": list(db.execute(select(Carrier).where(Carrier.organisation_id == org.id)).scalars()),
            "pemasok": list(db.execute(select(Partner).where(Partner.organisation_id == org.id, Partner.tipe == "supplier")).scalars()),
            "pelanggan": list(db.execute(select(Partner).where(Partner.organisation_id == org.id, Partner.tipe == "customer")).scalars())}


def stok_awal(db: Session, org: Organisation, items, gudang, tanggal: date) -> None:
    for item in items:
        record_movement(
            db, organisation_id=org.id, item_id=item.id, warehouse_id=gudang.id,
            qty=Decimal("300"), ref_type="opening", note="Stok awal data demo",
        )
    db.commit()
    db.execute(
        update(StockMovement)
        .where(StockMovement.organisation_id == org.id, StockMovement.ref_type == "opening")
        .values(created_at=_dt(tanggal, 7))
    )
    db.commit()


def _safety_stok(db: Session, org: Organisation, item_id, wh_id, butuh: Decimal) -> None:
    if stock_of(db, org.id, item_id, wh_id) < butuh:
        record_movement(
            db, organisation_id=org.id, item_id=item_id, warehouse_id=wh_id,
            qty=butuh * 3, ref_type="adjustment", note="Penyesuaian data demo",
        )
        db.commit()


# --------------------------------------------------------------- transaksi
def _hari_acak(rng: random.Random, y: int, m: int, batas: date) -> date:
    akhir = calendar.monthrange(y, m)[1]
    maks = akhir
    if (y, m) == (batas.year, batas.month):
        maks = min(maks, batas.day)
    return date(y, m, rng.randint(1, max(1, maks)))


def _cap(d: date, hari: int, batas: date) -> date:
    hasil = d + timedelta(days=hari)
    return min(hasil, batas)


def transaksi(
    db: Session, org: Organisation, *, tahun: int, rng: random.Random, refs: dict, user_id
) -> dict[str, int]:
    batas = date.today()
    mulai = date(batas.year - tahun, batas.month, 1)
    gudang_utama = next(g for g in refs["gudang"] if g.is_default)
    items = [i for i in refs["items"] if i.tipe == "produk"]
    armada = refs["armada"]
    ekspedisi = refs["ekspedisi"]

    n = {"po": 0, "so": 0, "faktur_beli": 0, "faktur_jual": 0, "pengiriman": 0, "rute": 0, "bayar": 0}
    bulan_ke = 0

    for y, m in _bulan_rentang(mulai, batas):
        bulan_ke += 1
        # -------- pembelian -------------------------------------------------
        for _ in range(rng.randint(2, 4)):
            tanggal = _hari_acak(rng, y, m, batas)
            paksa_tanggal(tanggal)
            baris = []
            for item in rng.sample(items, rng.randint(1, 3)):
                qty = Decimal(rng.randint(20, 80))
                harga = _r2(item.harga_beli * Decimal(str(rng.uniform(0.95, 1.05))))
                baris.append({"item_id": item.id, "qty": qty, "harga": harga})
            po = buat_po(
                db, organisation_id=org.id, user_id=user_id,
                supplier_id=rng.choice(refs["pemasok"]).id,
                warehouse_id=gudang_utama.id, tanggal=tanggal,
                catatan="Data demo", lines=baris,
            )
            po.created_at = _dt(tanggal, 9)
            terima_po(db, organisation_id=org.id, user_id=user_id, order_id=po.id)
            po.received_at = _dt(_cap(tanggal, rng.randint(1, 5), batas), 14)
            db.commit()
            db.execute(
                update(StockMovement)
                .where(StockMovement.ref_type == "purchase_receipt", StockMovement.ref_id == po.id)
                .values(created_at=po.received_at)
            )
            db.commit()
            n["po"] += 1

            tgl_faktur = _cap(tanggal, rng.randint(2, 6), batas)
            paksa_tanggal(tgl_faktur)
            fb = buat_faktur_beli(
                db, organisation_id=org.id, user_id=user_id, order_id=po.id,
                tanggal=tgl_faktur, jatuh_tempo=_cap(tgl_faktur, 30, batas),
                supplier_ref=f"INV/{tgl_faktur.year}/{rng.randint(100, 999)}",
            )
            fb.created_at = _dt(tgl_faktur, 11)
            db.commit()
            n["faktur_beli"] += 1

            if rng.random() < 0.85:
                tgl_bayar = _cap(tgl_faktur, rng.randint(3, 40), batas)
                paksa_tanggal(tgl_bayar)
                bayar_beli(db, organisation_id=org.id, invoice_id=fb.id, user_id=user_id, tanggal=tgl_bayar)
                fb.paid_at = _dt(tgl_bayar, 13)
                db.commit()
                n["bayar"] += 1

        # -------- penjualan -------------------------------------------------
        for _ in range(rng.randint(3, 5)):
            tanggal = _hari_acak(rng, y, m, batas)
            paksa_tanggal(tanggal)
            baris = []
            for item in rng.sample(items, rng.randint(1, 3)):
                qty = Decimal(rng.randint(5, 25))
                _safety_stok(db, org, item.id, gudang_utama.id, qty)
                harga = _r2(item.harga_jual * Decimal(str(rng.uniform(0.97, 1.03))))
                baris.append({"item_id": item.id, "qty": qty, "harga": harga})
            so = buat_so(
                db, organisation_id=org.id, user_id=user_id,
                customer_id=rng.choice(refs["pelanggan"]).id,
                warehouse_id=gudang_utama.id, tanggal=tanggal,
                catatan="Data demo", lines=baris,
            )
            so.created_at = _dt(tanggal, 8)
            kirim_so(db, organisation_id=org.id, user_id=user_id, order_id=so.id)
            so.delivered_at = _dt(_cap(tanggal, rng.randint(1, 4), batas), 15)
            db.commit()
            db.execute(
                update(StockMovement)
                .where(StockMovement.ref_type == "sales_delivery", StockMovement.ref_id == so.id)
                .values(created_at=so.delivered_at)
            )
            db.commit()
            n["so"] += 1

            # surat jalan (sebagian SO)
            if rng.random() < 0.6:
                so_id = so.id
                kendaraan = rng.choice(armada) if rng.random() < 0.7 else None
                eksp = None if kendaraan is not None and rng.random() < 0.5 else rng.choice(ekspedisi)
                resi = f"RESI{tanggal.strftime('%y%m%d')}{rng.randint(1000, 9999)}"
                try:
                    sj = create_shipment_from_order(
                        db, organisation_id=org.id, user_id=user_id, order_id=so_id,
                        vehicle_id=kendaraan.id if kendaraan else None,
                        carrier_id=eksp.id if eksp else None,
                        resi=resi,
                    )
                except Exception:  # noqa: BLE001 — kapasitas armada, coba tanpa kendaraan
                    db.rollback()
                    sj = create_shipment_from_order(
                        db, organisation_id=org.id, user_id=user_id, order_id=so_id,
                        resi=resi,
                    )
                status = rng.choice(["delivered", "delivered", "in_transit"])
                update_status(
                    db, organisation_id=org.id, user_id=user_id, shipment_id=sj.id,
                    status=status, note="Data demo",
                )
                sj.created_at = _dt(tanggal, 9, 30)
                sj.shipped_at = _dt(_cap(tanggal, 1, batas), 8)
                if status == "delivered":
                    sj.delivered_at = _dt(_cap(tanggal, rng.randint(1, 4), batas), 16)
                db.commit()
                n["pengiriman"] += 1

            tgl_faktur = _cap(tanggal, rng.randint(1, 5), batas)
            paksa_tanggal(tgl_faktur)
            fj = buat_faktur_jual(
                db, organisation_id=org.id, user_id=user_id, order_id=so.id,
                tanggal=tgl_faktur, jatuh_tempo=_cap(tgl_faktur, 30, batas),
            )
            fj.created_at = _dt(tgl_faktur, 12)
            db.commit()
            n["faktur_jual"] += 1

            if rng.random() < 0.85:
                tgl_bayar = _cap(tgl_faktur, rng.randint(3, 40), batas)
                paksa_tanggal(tgl_bayar)
                bayar_jual(db, organisation_id=org.id, invoice_id=fj.id, user_id=user_id, tanggal=tgl_bayar)
                fj.paid_at = _dt(tgl_bayar, 14)
                db.commit()
                n["bayar"] += 1

        # -------- rute harian ----------------------------------------------
        for _ in range(rng.randint(1, 2)):
            tanggal = _hari_acak(rng, y, m, batas)
            paksa_tanggal(tanggal)
            kendaraan = rng.choice(armada)
            status = rng.choice(["selesai", "selesai", "berjalan"])
            rute = save_route(
                db, org.id,
                {"nama": f"Rute {kendaraan.nama} {tanggal.strftime('%d/%m')}",
                 "tanggal": tanggal, "vehicle_id": str(kendaraan.id),
                 "status": status, "catatan": "Data demo"},
                user_id=user_id,
            )
            rute.created_at = _dt(tanggal, 7, 30)
            db.commit()
            for alamat, jarak in rng.sample(
                [(p.alamat or p.nama, round(rng.uniform(3, 25), 1)) for p in refs["pelanggan"]],
                rng.randint(2, 3),
            ):
                stop = add_stop(
                    db, organisation_id=org.id, route_id=rute.id,
                    alamat=alamat, jarak_km=str(jarak), catatan="Data demo",
                )
                if status == "selesai":
                    update_stop_status(db, organisation_id=org.id, stop_id=stop.id, status="tiba")
            db.commit()
            n["rute"] += 1

        if bulan_ke % 12 == 0:
            print(f"    … {y}-{m:02d} selesai (PO {n['po']}, SO {n['so']})")

    paksa_tanggal(batas)
    return n


# ------------------------------------------------------------------- ringkas
def ringkas(db: Session, org: Organisation) -> None:
    print("\nRingkasan data:")
    for tabel in [
        "partners", "items", "warehouses", "vehicles", "carriers", "stock_movements",
        "purchase_orders", "purchase_invoices", "sales_orders", "sales_invoices",
        "shipments", "routes", "payments", "journal_entries",
    ]:
        jumlah = db.execute(
            text(f"SELECT count(*) FROM {tabel} WHERE organisation_id = :org"), {"org": org.id}
        ).scalar()
        print(f"  {tabel:20} {jumlah}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed data demo 5 tahun REPTIL")
    parser.add_argument("--org", default="REPTIL")
    parser.add_argument("--org-name", default="PT Reptil Nusantara")
    parser.add_argument("--password", default="Reptil#2026", help="kata sandi semua pengguna demo")
    parser.add_argument("--years", type=int, default=5, help="rentang tahun transaksi")
    parser.add_argument("--seed", type=int, default=20261017, help="benih angka acak")
    parser.add_argument("--reset", action="store_true", help="hapus data transaksi lalu buat ulang")
    parser.add_argument("--tanpa-transaksi", action="store_true", help="hanya peran/pengguna/master data")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    db = SessionLocal()
    try:
        org = db.execute(
            select(Organisation).where(Organisation.code == args.org.upper())
        ).scalar_one_or_none()
        if org is None:
            print(f"Organisasi '{args.org}' tidak ada. Jalankan scripts/seed_admin.py dulu.")
            return 1

        print("1. Peran")
        peran = siapkan_peran(db, org)
        print("2. Pengguna")
        pengguna = siapkan_pengguna(db, org, peran, args.password)
        print("3. Master data")
        refs = siapkan_master(db, org)

        from reptil.modules.finance.service import pastikan_coa  # noqa: PLC0415

        pastikan_coa(db, org.id)
        db.commit()

        sudah_ada = db.execute(
            select(func.count()).select_from(StockMovement).where(
                StockMovement.organisation_id == org.id, StockMovement.ref_type.in_(["purchase_receipt", "sales_delivery"])
            )
        ).scalar_one()

        if args.tanpa_transaksi:
            print("4. Transaksi: dilewati (--tanpa-transaksi)")
        else:
            if args.reset:
                reset_transaksi(db, org)
                sudah_ada = 0
            elif sudah_ada:
                print(f"4. Transaksi: DILEWATI — sudah ada data ({sudah_ada} mutasi). Pakai --reset untuk buat ulang.")
            if not sudah_ada:
                print(f"4. Transaksi {args.years} tahun — mulai {date.today().year - args.years}-{date.today().month:02d} s/d sekarang")
                mulai = date(date.today().year - args.years, date.today().month, 1)
                stok_awal(db, org, refs["items"], next(g for g in refs["gudang"] if g.is_default), mulai)
                jumlah = transaksi(
                    db, org, tahun=args.years, rng=rng, refs=refs,
                    user_id=pengguna["admin@reptil.co.id"].id,
                )
                print(
                    f"   selesai: PO {jumlah['po']}, faktur beli {jumlah['faktur_beli']}, "
                    f"SO {jumlah['so']}, faktur jual {jumlah['faktur_jual']}, "
                    f"pengiriman {jumlah['pengiriman']}, rute {jumlah['rute']}, pembayaran {jumlah['bayar']}"
                )

        ringkas(db, org)
        print("\nAkun demo (kata sandi sama):")
        for email, _nama, _peran in PENGGUNA:
            print(f"  {email:28} {args.password}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
