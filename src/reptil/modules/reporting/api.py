"""API JSON laporan: ringkasan, penjualan, laba-rugi, nilai stok, ekspor (Swagger)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from reptil.api.common import SkemaOut
from reptil.core.db import get_db
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.reporting import service as rl

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

BACA = require_permission("reports.read")


def _rentang(dari: date | None, sampai: date | None) -> tuple[date, date]:
    """Rentang laporan; kosong = bulan berjalan. Bila terbalik, ditukar."""
    awal, akhir = rl.rentang_bulan_ini()
    tanggal_dari = dari or awal
    tanggal_sampai = sampai or akhir
    if tanggal_dari > tanggal_sampai:
        tanggal_dari, tanggal_sampai = tanggal_sampai, tanggal_dari
    return tanggal_dari, tanggal_sampai


class LabaRugiBarisOut(SkemaOut):
    kode: str
    nama: str
    nilai: Decimal


class LabaRugiOut(SkemaOut):
    pendapatan: list[LabaRugiBarisOut]
    beban: list[LabaRugiBarisOut]
    total_pendapatan: Decimal
    total_beban: Decimal
    laba: Decimal


class NilaiStokBarisOut(SkemaOut):
    item_id: uuid.UUID
    sku: str
    nama: str
    satuan: str
    qty: Decimal
    harga_beli: Decimal
    harga_jual: Decimal
    nilai_beli: Decimal
    nilai_jual: Decimal
    di_bawah_minimum: bool


class NilaiStokOut(SkemaOut):
    baris: list[NilaiStokBarisOut]
    total_nilai_beli: Decimal
    total_nilai_jual: Decimal
    total_item: int
    item_minimum: int


@router.get("/summary", summary="Ringkasan laporan")
def summary(
    dari: date | None = None,
    sampai: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    awal, akhir = _rentang(dari, sampai)
    return rl.rekap(db, user.organisation_id, awal, akhir)


@router.get("/sales-by-period", summary="Penjualan per periode")
def sales_by_period(
    dari: date | None = None,
    sampai: date | None = None,
    kelompok: str = Query("hari", description="hari | bulan"),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> list:
    awal, akhir = _rentang(dari, sampai)
    return rl.penjualan_per_periode(db, user.organisation_id, awal, akhir, kelompok)


@router.get("/sales-by-item", summary="Penjualan per item")
def sales_by_item(
    dari: date | None = None,
    sampai: date | None = None,
    batas: int = Query(25, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> list:
    awal, akhir = _rentang(dari, sampai)
    return rl.penjualan_per_item(db, user.organisation_id, awal, akhir, batas)


@router.get("/sales-by-customer", summary="Penjualan per pelanggan")
def sales_by_customer(
    dari: date | None = None,
    sampai: date | None = None,
    batas: int = Query(25, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> list:
    awal, akhir = _rentang(dari, sampai)
    return rl.penjualan_per_pelanggan(db, user.organisation_id, awal, akhir, batas)


@router.get("/profit-loss", response_model=LabaRugiOut, summary="Laba rugi")
def profit_loss(
    dari: date | None = None,
    sampai: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    awal, akhir = _rentang(dari, sampai)
    lr = rl.laba_rugi(db, user.organisation_id, awal, akhir)

    def baris(daftar: list[dict]) -> list[dict]:
        return [
            {"kode": b["akun"].kode, "nama": b["akun"].nama, "nilai": b["nilai"]} for b in daftar
        ]

    return {
        "pendapatan": baris(lr["pendapatan"]),
        "beban": baris(lr["beban"]),
        "total_pendapatan": lr["total_pendapatan"],
        "total_beban": lr["total_beban"],
        "laba": lr["laba"],
    }


@router.get("/stock-value", response_model=NilaiStokOut, summary="Nilai persediaan")
def stock_value(db: Session = Depends(get_db), user: User = Depends(BACA)) -> dict:
    data = rl.nilai_stok(db, user.organisation_id)
    return {
        "baris": [
            {
                "item_id": b["item"].id,
                "sku": b["item"].sku,
                "nama": b["item"].nama,
                "satuan": b["item"].satuan,
                "qty": b["qty"],
                "harga_beli": b["harga_beli"],
                "harga_jual": b["harga_jual"],
                "nilai_beli": b["nilai_beli"],
                "nilai_jual": b["nilai_jual"],
                "di_bawah_minimum": b["di_bawah_minimum"],
            }
            for b in data["baris"]
        ],
        "total_nilai_beli": data["total_nilai_beli"],
        "total_nilai_jual": data["total_nilai_jual"],
        "total_item": data["total_item"],
        "item_minimum": data["item_minimum"],
    }


@router.get("/export/{kode}", summary="Ekspor laporan (xlsx/csv)")
def export(
    kode: str = Path(..., description="Kode ekspor, mis. stok | faktur_jual | utang"),
    dari: date | None = None,
    sampai: date | None = None,
    format: str = Query("xlsx", description="xlsx | csv"),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> Response:
    awal, akhir = _rentang(dari, sampai)
    isi, media, nama = rl.ekspor(db, user.organisation_id, kode, awal, akhir, format)
    return Response(
        content=isi,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )
