"""Instance Jinja2Templates bersama + filter tampilan (rupiah, tanggal, qty)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi.templating import Jinja2Templates

from reptil.core.pdf import rupiah as _rupiah
from reptil.core.pdf import tanggal_id as _tanggal_id

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def qty(value: Decimal | float | int | None) -> str:
    """Tampilkan qty tanpa nol ekor: 12.000 → '12', 2.500 → '2,5'."""
    if value is None:
        return "0"
    try:
        n = Decimal(str(value)).normalize()
    except InvalidOperation:
        return str(value)
    teks = f"{n:f}"
    return teks.rstrip("0").rstrip(".") if "." in teks else teks


def rupiah_filter(value) -> str:
    if value is None:
        value = 0
    return "Rp " + _rupiah(value)


templates.env.filters["rupiah"] = rupiah_filter
templates.env.filters["angka_rupiah"] = _rupiah           # tanpa prefix Rp
templates.env.filters["tanggal_id"] = _tanggal_id
templates.env.filters["qty"] = qty
