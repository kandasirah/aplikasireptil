"""Informasi sistem untuk footer: versi, lingkungan, database, waktu server."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from sys import version_info as sys_version_info

from sqlalchemy import text

from reptil import __version__
from reptil.core.config import get_settings
from reptil.core.db import engine

try:
    from zoneinfo import ZoneInfo

    ZONA = ZoneInfo("Asia/Jakarta")
    LABEL_ZONA = "WIB"
except Exception:  # pragma: no cover — sistem tanpa tzdata
    ZONA, LABEL_ZONA = UTC, "UTC"


@lru_cache(maxsize=1)
def versi_database() -> str:
    """Versi server basis data (di-cache: jarang berubah)."""
    try:
        with engine.connect() as conn:
            lengkap = conn.execute(text("SELECT version()")).scalar() or ""
    except Exception as exc:  # noqa: BLE001
        return f"tidak terhubung ({type(exc).__name__})"
    # "PostgreSQL 14.24 on x86_64-pc-linux-musl, compiled by gcc ..." → "PostgreSQL 14.24"
    return lengkap.split(" on ")[0].strip() or "tidak diketahui"


def waktu_sekarang() -> datetime:
    return datetime.now(ZONA)


def info_sistem(nama_aplikasi: str | None = None) -> dict:
    """Ringkasan untuk footer dashboard & halaman informasi sistem."""
    settings = get_settings()
    return {
        "aplikasi": nama_aplikasi or settings.app_name,
        "versi": __version__,
        "lingkungan": settings.app_env,
        "database": versi_database(),
        "waktu": waktu_sekarang().strftime("%d %b %Y %H:%M"),
        "zona": LABEL_ZONA,
        "python": f"{sys_version_info.major}.{sys_version_info.minor}.{sys_version_info.micro}",
    }
