"""Penomoran dokumen otomatis: PREFIX-TAHUN-URUT (mis. SO-2026-0001)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reptil.core.errors import ConflictError


def next_number(db: Session, model, organisation_id: uuid.UUID, prefix: str) -> str:
    """Nomor berikutnya untuk dokumen (berdasarkan nomor tertinggi tahun berjalan)."""
    pattern = f"{prefix}-{date.today().year}-%"
    last = db.execute(
        select(func.max(model.number)).where(
            model.organisation_id == organisation_id, model.number.like(pattern)
        )
    ).scalar()
    seq = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
    return f"{prefix}-{date.today().year}-{seq:04d}"


def next_number_safe(
    db: Session, model, organisation_id: uuid.UUID, prefix: str, attempts: int = 5
) -> str:
    """Ambil nomor bebas bentrok. Pemanggil tetap wajib punya unique constraint."""
    number = next_number(db, model, organisation_id, prefix)
    for _ in range(attempts):
        exists = db.execute(
            select(model.id).where(
                model.organisation_id == organisation_id, model.number == number
            )
        ).first()
        if not exists:
            return number
        number = next_number(db, model, organisation_id, prefix)
    raise ConflictError("Gagal membuat nomor dokumen (bentrok berulang).")
