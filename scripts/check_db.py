#!/usr/bin/env python3
"""Cek koneksi database REPTIL.

Jalankan:  .venv/bin/python scripts/check_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reptil.core.db import check_connection  # noqa: E402


def main() -> int:
    try:
        info = check_connection()
    except Exception as exc:  # noqa: BLE001 — tujuan skrip memang menampilkan error
        print(f"GAGAL terhubung: {exc}")
        return 1

    print("Koneksi OK")
    print(f"  host    : {info['host']}")
    print(f"  database: {info['database']}")
    print(f"  user    : {info['user']}")
    print(f"  server  : {info['server_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
