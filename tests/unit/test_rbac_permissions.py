"""Uji katalog izin RBAC (tanpa DB)."""

from __future__ import annotations

from reptil.modules.identity.permissions import (
    KATALOG,
    WILDCARD,
    kode_tidak_dikenal,
    kode_valid,
    label_dari_kode,
    normalisasi,
    semua_kode,
)


def test_katalog_tidak_ada_kode_duplikat() -> None:
    kode = semua_kode()
    assert len(kode) == len(set(kode))
    assert kode_valid() == set(kode)


def test_katalog_memuat_semua_izin_uang_dipakai_modul() -> None:
    """Setiap kode yang dicek guard halaman harus ada di katalog."""
    dipakai = {
        "masterdata.read",
        "masterdata.write",
        "purchasing.read",
        "purchasing.write",
        "sales.read",
        "sales.write",
        "inventory.read",
        "inventory.write",
        "logistics.read",
        "logistics.write",
        "finance.read",
        "finance.write",
        "users.read",
        "users.write",
        "roles.read",
        "roles.write",
        "settings.read",
        "settings.write",
    }
    assert dipakai <= kode_valid()


def test_normalisasi_membuang_kode_asing_dan_duplikat() -> None:
    hasil = normalisasi(["sales.read", "tidak.ada", "sales.read", "masterdata.read", ""])
    # urut sesuai katalog (masterdata sebelum sales) & tanpa duplikat
    assert hasil == ["masterdata.read", "sales.read"]


def test_normalisasi_none_dan_kosong() -> None:
    assert normalisasi(None) == []
    assert normalisasi([]) == []


def test_kode_tidak_dikenal_abaikan_wildcard() -> None:
    assert kode_tidak_dikenal(["*", "sales.read", "x.y"]) == {"x.y"}
    assert kode_tidak_dikenal(None) == set()


def test_label_dari_kode() -> None:
    assert label_dari_kode(WILDCARD) == "Akses penuh (semua menu)"
    assert label_dari_kode("sales.read") == "Lihat dokumen penjualan"
    # kode tak dikenal dikembalikan apa adanya
    assert label_dari_kode("x.y") == "x.y"


def test_setiap_grup_punya_izin() -> None:
    for grup in KATALOG:
        assert grup.nama and grup.keterangan
        assert grup.izin, f"grup {grup.nama} kosong"
        for izin in grup.izin:
            assert "." in izin.code and izin.label
