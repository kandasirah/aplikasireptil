"""Konversi angka ke terbilang Bahasa Indonesia (untuk baris 'Terbilang' di faktur)."""

from __future__ import annotations

from decimal import Decimal

_SATUAN = [
    "", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan",
    "sembilan", "sepuluh", "sebelas",
]


def _terbilang_bulat(n: int) -> str:
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_terbilang_bulat(n - 10)} belas"
    if n < 100:
        return f"{_terbilang_bulat(n // 10)} puluh {_terbilang_bulat(n % 10)}".strip()
    if n < 200:
        return f"seratus {_terbilang_bulat(n - 100)}".strip()
    if n < 1_000:
        return f"{_terbilang_bulat(n // 100)} ratus {_terbilang_bulat(n % 100)}".strip()
    if n < 2_000:
        return f"seribu {_terbilang_bulat(n - 1_000)}".strip()
    for pembagi, sebutan in ((1_000_000_000_000, "triliun"), (1_000_000_000, "miliar"),
                             (1_000_000, "juta"), (1_000, "ribu")):
        if n >= pembagi:
            sisa = n % pembagi
            return f"{_terbilang_bulat(n // pembagi)} {sebutan} {_terbilang_bulat(sisa)}".strip()
    return _SATUAN[0]


def terbilang_rupiah(nilai: Decimal | float | int) -> str:
    """Contoh: 1_250_000 → 'Satu juta dua ratus lima puluh ribu rupiah'."""
    nilai = Decimal(str(nilai)).quantize(Decimal("1"))
    if nilai == 0:
        return "Nol rupiah"
    kata = _terbilang_bulat(abs(int(nilai)))
    kata = " ".join(kata.split())  # rapikan spasi ganda
    hasil = f"{kata} rupiah"
    if nilai < 0:
        hasil = f"minus {hasil}"
    return hasil[0].upper() + hasil[1:]
