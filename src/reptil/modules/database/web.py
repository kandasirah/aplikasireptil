"""Halaman web Manajemen Database: statistik, reset data, dan data demo."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from reptil.core.config import get_settings
from reptil.core.db import get_db
from reptil.modules.database import service as svc
from reptil.modules.database.models import LABEL_JENIS, LABEL_STATUS
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render

router = APIRouter(tags=["web-database"])

IZIN_LIHAT = "database.read"
IZIN_UBAH = "database.write"

FRASA_DEMO = "BUAT DEMO"
FRASA_RESET = "HAPUS DATA"

PILIHAN_BULAN = ((12, "1 tahun"), (36, "3 tahun"), (60, "5 tahun (disarankan)"), (120, "10 tahun"))
PILIHAN_KEPADATAN = (
    (6, "Ringan — 6 faktur/bulan"),
    (12, "Sedang — 12 faktur/bulan"),
    (25, "Padat — 25 faktur/bulan"),
    (40, "Sangat padat — 40 faktur/bulan"),
)
PILIHAN_SKALA = (("0.5", "Kecil"), ("1", "Sedang"), ("2.5", "Besar"))


def _guard(request: Request, db: Session, izin: str = IZIN_LIHAT):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


def _konteks_dasar() -> dict:
    settings = get_settings()
    return {
        "pilihan_bulan": PILIHAN_BULAN,
        "pilihan_kepadatan": PILIHAN_KEPADATAN,
        "pilihan_skala": PILIHAN_SKALA,
        "label_mode": svc.LABEL_MODE,
        "keterangan_mode": svc.KETERANGAN_MODE,
        "frasa_demo": FRASA_DEMO,
        "frasa_reset": FRASA_RESET,
        "info_db": {
            "nama": settings.database_name,
            "host": settings.database_host,
            "port": settings.database_port,
            "user": settings.database_user,
        },
    }


@router.get("/database", response_class=HTMLResponse, include_in_schema=False)
def halaman_database(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    from reptil.modules.finance import service as fin

    org = user.organisation_id
    pratinjau = {mode: svc.ringkasan_hapus(db, org, mode) for mode in svc.MODE_HAPUS}
    return render(
        request,
        "database/index.html",
        user,
        "database",
        statistik=svc.statistik(db, org),
        kesehatan=svc.kesehatan(db, org),
        pratinjau=pratinjau,
        ringkas=fin.ringkasan(db, org),
        pekerjaan=svc.daftar_job(db, org, batas=8),
        job_aktif=svc.job_berjalan(db, org),
        label_jenis=LABEL_JENIS,
        label_status=LABEL_STATUS,
        boleh_ubah=has(user, IZIN_UBAH),
        perkiraan=svc.perkiraan_demo(
            {"bulan": 60, "per_bulan": 12, "skala": "1", "logistik": True}
        ),
        **_konteks_dasar(),
    )


@router.post("/database/demo", include_in_schema=False)
def mulai_demo(
    request: Request,
    bulan: int = Form(60),
    per_bulan: int = Form(12),
    skala: str = Form("1"),
    seed: int = Form(20261017),
    logistik: str = Form(""),
    bersihkan: str = Form(""),
    konfirmasi: str = Form(""),
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db, IZIN_UBAH)
    if err:
        return err
    if konfirmasi.strip().upper() != FRASA_DEMO:
        return flash_err("/database", f"Konfirmasi salah. Ketik tepat: {FRASA_DEMO}")
    if svc.job_berjalan(db, user.organisation_id):
        return flash_err("/database", "Masih ada proses berjalan — tunggu sampai selesai.")

    parameter = {
        "bulan": max(1, min(int(bulan), 120)),
        "per_bulan": max(1, min(int(per_bulan), 40)),
        "skala": skala,
        "seed": int(seed),
        "logistik": bool(logistik),
        "bersihkan": bool(bersihkan),
        "mode_hapus": "transaksi",
    }
    job = svc.mulai_job(
        organisation_id=user.organisation_id,
        jenis="demo",
        parameter=parameter,
        user_id=user.id,
    )
    return flash_ok(f"/database/jobs/{job.id}", "Pembuatan data demo dimulai…")


@router.post("/database/reset", include_in_schema=False)
def mulai_reset(
    request: Request,
    mode: str = Form("transaksi"),
    konfirmasi: str = Form(""),
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db, IZIN_UBAH)
    if err:
        return err
    if mode not in svc.MODE_HAPUS:
        return flash_err("/database", "Mode penghapusan tidak dikenal.")
    if konfirmasi.strip().upper() != FRASA_RESET:
        return flash_err("/database", f"Konfirmasi salah. Ketik tepat: {FRASA_RESET}")
    if svc.job_berjalan(db, user.organisation_id):
        return flash_err("/database", "Masih ada proses berjalan — tunggu sampai selesai.")

    job = svc.mulai_job(
        organisation_id=user.organisation_id,
        jenis="reset",
        parameter={"mode": mode},
        user_id=user.id,
    )
    return flash_ok(f"/database/jobs/{job.id}", f"{svc.LABEL_MODE[mode]} dimulai…")


@router.get("/database/jobs", response_class=HTMLResponse, include_in_schema=False)
def daftar_pekerjaan(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    return render(
        request,
        "database/jobs.html",
        user,
        "database",
        pekerjaan=svc.daftar_job(db, user.organisation_id, batas=100),
        label_jenis=LABEL_JENIS,
        label_status=LABEL_STATUS,
        **_konteks_dasar(),
    )


@router.get("/database/jobs/{job_id}", response_class=HTMLResponse, include_in_schema=False)
def halaman_pekerjaan(job_id: str, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    pekerjaan = _ambil_job(db, user.organisation_id, job_id)
    if pekerjaan is None:
        return flash_err("/database", "Pekerjaan tidak ditemukan.")
    return render(
        request,
        "database/job.html",
        user,
        "database",
        pekerjaan=pekerjaan,
        label_jenis=LABEL_JENIS,
        label_status=LABEL_STATUS,
        **_konteks_dasar(),
    )


@router.get("/database/jobs/{job_id}/status", include_in_schema=False)
def status_pekerjaan(job_id: str, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return JSONResponse({"ada": False}, status_code=403)
    pekerjaan = _ambil_job(db, user.organisation_id, job_id)
    if pekerjaan is None:
        return JSONResponse({"ada": False}, status_code=404)
    return JSONResponse(
        {
            "ada": True,
            "status": pekerjaan.status,
            "label_status": LABEL_STATUS.get(pekerjaan.status, pekerjaan.status),
            "persen": pekerjaan.persen,
            "tahap": pekerjaan.tahap or "",
            "pesan": pekerjaan.pesan or "",
            "hasil": pekerjaan.hasil,
            "selesai": pekerjaan.status in ("selesai", "gagal"),
            "selesai_pada": pekerjaan.selesai_pada.isoformat() if pekerjaan.selesai_pada else None,
        }
    )


def _ambil_job(db: Session, organisation_id: uuid.UUID, job_id: str):
    try:
        kunci = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return None
    return svc.get_job(db, organisation_id, kunci)
