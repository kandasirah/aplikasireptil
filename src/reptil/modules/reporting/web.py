"""Halaman web laporan: ringkasan, penjualan, laba-rugi, nilai persediaan, dan ekspor."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import AppError
from reptil.core.parsing import to_date
from reptil.modules.reporting import service as rl
from reptil.web.common import flash_err, has, page_user, redirect_login, render

router = APIRouter(tags=["web-reporting"])
IZIN = "reports.read"


def _guard(request: Request, db: Session):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    if not has(user, IZIN):
        return None, flash_err("/dashboard", f"Anda punya izin '{IZIN}'.")
    return user, None


def _rentang(dari: str, sampai: str) -> tuple[date, date]:
    """Rentang laporan; kosong berarti bulan berjalan. Bila terbalik, ditukar."""
    awal, akhir = rl.rentang_bulan_ini()
    tanggal_dari = to_date(dari, "Dari", default=awal)
    tanggal_sampai = to_date(sampai, "Sampai", default=akhir)
    if tanggal_dari > tanggal_sampai:
        tanggal_dari, tanggal_sampai = tanggal_sampai, tanggal_dari
    return tanggal_dari, tanggal_sampai


def _konteks(dari: date, sampai: date) -> dict:
    return {
        "dari": dari.isoformat(),
        "sampai": sampai.isoformat(),
        "daftar_ekspor": list(rl.EKSPOR.values()),
        "LABEL_KELOMPOK": rl.LABEL_KELOMPOK,
    }


@router.get("/reports", response_class=HTMLResponse, include_in_schema=False)
def reports_page(request: Request, dari: str = "", sampai: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    tanggal_dari, tanggal_sampai = _rentang(dari, sampai)
    return render(
        request,
        "reports/index.html",
        user,
        "reports",
        rekap=rl.rekap(db, user.organisation_id, tanggal_dari, tanggal_sampai),
        harian=rl.penjualan_per_periode(
            db, user.organisation_id, tanggal_dari, tanggal_sampai, "hari"
        ),
        per_item=rl.penjualan_per_item(
            db, user.organisation_id, tanggal_dari, tanggal_sampai, batas=8
        ),
        **_konteks(tanggal_dari, tanggal_sampai),
    )


@router.get("/reports/sales", response_class=HTMLResponse, include_in_schema=False)
def sales_report(
    request: Request,
    dari: str = "",
    sampai: str = "",
    kelompok: str = "hari",
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db)
    if err:
        return err
    tanggal_dari, tanggal_sampai = _rentang(dari, sampai)
    if kelompok not in rl.KELOMPOK_PERIODE:
        kelompok = "hari"
    periode = rl.penjualan_per_periode(
        db, user.organisation_id, tanggal_dari, tanggal_sampai, kelompok
    )
    return render(
        request,
        "reports/sales.html",
        user,
        "reports-penjualan",
        kelompok=kelompok,
        periode=periode,
        per_item=rl.penjualan_per_item(db, user.organisation_id, tanggal_dari, tanggal_sampai),
        per_pelanggan=rl.penjualan_per_pelanggan(
            db, user.organisation_id, tanggal_dari, tanggal_sampai
        ),
        total=sum((b["total"] for b in periode), rl.NOL),
        jumlah_faktur=sum(b["jumlah"] for b in periode),
        **_konteks(tanggal_dari, tanggal_sampai),
    )


@router.get("/reports/profit-loss", response_class=HTMLResponse, include_in_schema=False)
def profit_loss_page(
    request: Request, dari: str = "", sampai: str = "", db: Session = Depends(get_db)
):
    user, err = _guard(request, db)
    if err:
        return err
    tanggal_dari, tanggal_sampai = _rentang(dari, sampai)
    return render(
        request,
        "reports/profit_loss.html",
        user,
        "reports-laba",
        laba_rugi=rl.laba_rugi(db, user.organisation_id, tanggal_dari, tanggal_sampai),
        hpp=rl.hpp_periode(db, user.organisation_id, tanggal_dari, tanggal_sampai),
        **_konteks(tanggal_dari, tanggal_sampai),
    )


@router.get("/reports/stock", response_class=HTMLResponse, include_in_schema=False)
def stock_report(request: Request, dari: str = "", sampai: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    tanggal_dari, tanggal_sampai = _rentang(dari, sampai)
    return render(
        request,
        "reports/stock.html",
        user,
        "reports-stok",
        persediaan=rl.nilai_stok(db, user.organisation_id),
        **_konteks(tanggal_dari, tanggal_sampai),
    )


@router.get("/reports/export/{kode}", include_in_schema=False)
def export_report(
    kode: str,
    request: Request,
    dari: str = "",
    sampai: str = "",
    format: str = "csv",
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db)
    if err:
        return err
    tanggal_dari, tanggal_sampai = _rentang(dari, sampai)
    try:
        isi, media_type, nama = rl.ekspor(
            db, user.organisation_id, kode, tanggal_dari, tanggal_sampai, format
        )
    except AppError as exc:
        return flash_err("/reports", str(exc))
    return Response(
        content=isi,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )
