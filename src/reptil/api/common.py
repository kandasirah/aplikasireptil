"""Utilitas bersama untuk endpoint JSON API (Swagger/OpenAPI).

Modul menyediakan router-nya sendiri lalu memakai helper di sini untuk hal yang
selalu sama: skema dasar Pydantic, batas paginasi, dan amplop daftar.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

BATAS_BAWAAN = 50
BATAS_MAKS = 500


class SkemaIn(BaseModel):
    """Dasar skema masukan (request body)."""


class SkemaOut(BaseModel):
    """Dasar skema keluaran; boleh dibangun langsung dari objek ORM."""

    model_config = ConfigDict(from_attributes=True)


class Halaman[T](BaseModel):
    """Amplop daftar berpaginasi: ``items`` + metadata."""

    items: list[T]
    total: int
    limit: int
    offset: int


def norma_batas(limit: int, offset: int) -> tuple[int, int]:
    """Jepit ``limit``/``offset`` ke rentang yang aman."""
    return max(1, min(limit, BATAS_MAKS)), max(0, offset)


def halaman(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    """Potong daftar menjadi satu halaman beserta metadatanya."""
    limit, offset = norma_batas(limit, offset)
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


__all__ = [
    "BATAS_BAWAAN",
    "BATAS_MAKS",
    "Halaman",
    "SkemaIn",
    "SkemaOut",
    "halaman",
    "norma_batas",
]
