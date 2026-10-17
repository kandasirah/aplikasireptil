"""Katalog izin (permission) REPTIL — sumber tunggal untuk UI centang & validasi.

Kode izin dipakai guard halaman (`has(user, "<kode>")`) dan disimpan apa adanya
di kolom JSONB ``roles.permissions``. Katalog ini membuat halaman Peran dapat
menampilkan centang yang benar-benar dikenali sistem, sekaligus menolak kode
asing yang salah ketik.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# "Akses penuh" — superadmin: boleh semua tanpa perlu centang satu-satu.
WILDCARD = "*"


@dataclass(frozen=True)
class Izin:
    """Satu izin: kode teknis + label manusiawi."""

    code: str
    label: str


@dataclass(frozen=True)
class GrupIzin:
    """Sekelompok izin yang ditampilkan bersama (per menu)."""

    nama: str
    keterangan: str
    izin: tuple[Izin, ...]


KATALOG: tuple[GrupIzin, ...] = (
    GrupIzin(
        "Master Data",
        "Partner, item, dan gudang.",
        (
            Izin("masterdata.read", "Lihat master data"),
            Izin("masterdata.write", "Tambah / ubah master data"),
        ),
    ),
    GrupIzin(
        "Pembelian",
        "Pesanan pembelian, penerimaan barang, dan faktur pembelian.",
        (
            Izin("purchasing.read", "Lihat dokumen pembelian"),
            Izin("purchasing.write", "Buat / proses dokumen pembelian"),
        ),
    ),
    GrupIzin(
        "Penjualan",
        "Pesanan penjualan, pengiriman barang, dan faktur penjualan.",
        (
            Izin("sales.read", "Lihat dokumen penjualan"),
            Izin("sales.write", "Buat / proses dokumen penjualan"),
        ),
    ),
    GrupIzin(
        "Persediaan",
        "Saldo stok, kartu stok, dan penyesuaian stok.",
        (
            Izin("inventory.read", "Lihat saldo & kartu stok"),
            Izin("inventory.write", "Penyesuaian / opname stok"),
        ),
    ),
    GrupIzin(
        "Logistik",
        "Pengiriman, armada, ekspedisi, dan rute.",
        (
            Izin("logistics.read", "Lihat pengiriman & rute"),
            Izin("logistics.write", "Kelola pengiriman & rute"),
        ),
    ),
    GrupIzin(
        "Pengguna & Hak Akses",
        "Kelola akun pengguna serta peran dan izinnya.",
        (
            Izin("users.read", "Lihat daftar pengguna"),
            Izin("users.write", "Tambah / ubah pengguna"),
            Izin("roles.read", "Lihat peran & izin"),
            Izin("roles.write", "Tambah / ubah peran & izin"),
        ),
    ),
    GrupIzin(
        "Keuangan",
        "Bagan akun, jurnal, utang-piutang, dan pembayaran.",
        (
            Izin("finance.read", "Lihat keuangan & laporan"),
            Izin("finance.write", "Kelola akun, jurnal & pembayaran"),
        ),
    ),
    GrupIzin(
        "Laporan",
        "Ringkasan penjualan, laba-rugi, nilai persediaan, dan ekspor.",
        (
            Izin("reports.read", "Lihat & ekspor laporan"),
        ),
    ),
    GrupIzin(
        "Pengaturan",
        "Profil aplikasi, identitas perusahaan, dan logo.",
        (
            Izin("settings.read", "Lihat pengaturan"),
            Izin("settings.write", "Ubah pengaturan"),
        ),
    ),
    GrupIzin(
        "Manajemen Database",
        "Reset data awal, pantau kesehatan data, dan buat data demo.",
        (
            Izin("database.read", "Lihat statistik & kesehatan data"),
            Izin("database.write", "Reset data & buat data demo"),
        ),
    ),
)

# Urutan kode mengikuti katalog — dipakai untuk normalisasi & tampilan.
_URUTAN: tuple[str, ...] = tuple(izin.code for grup in KATALOG for izin in grup.izin)
_LABEL: dict[str, str] = {izin.code: izin.label for grup in KATALOG for izin in grup.izin}


def kode_valid() -> set[str]:
    """Semua kode izin yang dikenali sistem."""
    return set(_URUTAN)


def semua_kode() -> list[str]:
    """Semua kode izin, urut sesuai katalog."""
    return list(_URUTAN)


def label_dari_kode(code: str) -> str:
    """Label manusiawi untuk sebuah kode; wildcard punya label khusus."""
    if code == WILDCARD:
        return "Akses penuh (semua menu)"
    return _LABEL.get(code, code)


def normalisasi(kode: Iterable[str] | None) -> list[str]:
    """Buang kode asing, hilangkan duplikat, lalu urutkan sesuai katalog."""
    dipilih = {k for k in (kode or ()) if k}
    return [code for code in _URUTAN if code in dipilih]


def kode_tidak_dikenal(kode: Iterable[str] | None) -> set[str]:
    """Kode yang tidak ada di katalog (untuk peringatan bila data lama tercemar)."""
    return {k for k in (kode or ()) if k and k != WILDCARD and k not in _LABEL}
