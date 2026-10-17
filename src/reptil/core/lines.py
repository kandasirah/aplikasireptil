"""Helper validasi baris dokumen (dipakai modul purchasing & sales)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from reptil.core.errors import BusinessRuleError
from reptil.core.parsing import to_decimal


def clean_lines(lines: list[dict], harga_field: str = "harga") -> list[dict]:
    """Bersihkan & validasi baris dokumen dari form/API.

    Baris tanpa item dilewati (memudahkan form dinamis), lalu qty & harga
    divalidasi. Subtotal dihitung di sini supaya konsisten di semua dokumen.
    """
    hasil: list[dict] = []
    for raw in lines:
        item_id = raw.get("item_id")
        if not item_id:
            continue
        qty = to_decimal(raw.get("qty"), "Qty")
        harga = to_decimal(raw.get(harga_field), "Harga", default=Decimal("0"))
        if qty <= 0:
            raise BusinessRuleError("Qty setiap baris harus lebih besar dari nol.")
        if harga < 0:
            raise BusinessRuleError("Harga tidak boleh negatif.")
        hasil.append(
            {
                "item_id": uuid.UUID(str(item_id)),
                "qty": qty,
                "harga": harga,
                "subtotal": (qty * harga).quantize(Decimal("0.01")),
                "catatan": (raw.get("catatan") or "").strip() or None,
            }
        )
    if not hasil:
        raise BusinessRuleError("Dokumen harus punya minimal satu baris item.")
    return hasil
