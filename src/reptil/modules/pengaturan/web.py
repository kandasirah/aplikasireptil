"""Halaman pengaturan profil aplikasi & perusahaan, serta penyajian logo."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError
from reptil.core.security import TOKEN_COOKIE_NAME, decode_access_token
from reptil.modules.pengaturan.models import AppSetting
from reptil.modules.pengaturan.service import baris_pengaturan, simpan_pengaturan
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render

router = APIRouter(tags=["web-pengaturan"])


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = "settings.write" if butuh_tulis else "settings.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


@router.get("/pengaturan", response_class=HTMLResponse, include_in_schema=False)
def pengaturan_page(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    return render(
        request, "pengaturan/form.html", user, "pengaturan",
        baris=baris_pengaturan(db, user.organisation_id),
    )


@router.post("/pengaturan", include_in_schema=False)
async def pengaturan_simpan(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err

    form = await request.form()
    try:
        simpan_pengaturan(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            data=dict(form),
            app_logo=await _baca_unggahan(form.get("app_logo")),
            company_logo=await _baca_unggahan(form.get("company_logo")),
            hapus_app_logo=bool(form.get("hapus_app_logo")),
            hapus_company_logo=bool(form.get("hapus_company_logo")),
            rev=(form.get("rev") or "").strip() or None,
        )
    except BusinessRuleError as exc:
        return flash_err("/pengaturan", str(exc))
    return flash_ok("/pengaturan", "Pengaturan disimpan.")


async def _baca_unggahan(berkas: object) -> tuple[bytes, str, str] | None:
    """Kembalikan (isi, mime, nama) bila ada berkas yang benar-benar diunggah.

    Catatan: berkas dari ``request.form()`` bertipe ``starlette.datastructures.UploadFile``,
    bukan ``fastapi.UploadFile`` — karena itu diperiksa berdasarkan sifatnya, bukan isinstance.
    """
    if not getattr(berkas, "filename", None) or not hasattr(berkas, "read"):
        return None
    isi = await berkas.read()
    if not isi:
        return None
    return isi, (getattr(berkas, "content_type", "") or "").lower(), str(berkas.filename)


@router.get("/logo/{jenis}", include_in_schema=False)
def logo(jenis: str, request: Request, db: Session = Depends(get_db), v: str = ""):
    """Sajikan logo langsung dari database (sidebar, halaman login, footer)."""
    if jenis not in ("aplikasi", "perusahaan"):
        return Response(status_code=404)

    baris: AppSetting | None = None
    payload = decode_access_token(request.cookies.get(TOKEN_COOKIE_NAME) or "")
    if payload and payload.get("org"):
        try:
            baris = baris_pengaturan(db, uuid.UUID(payload["org"]))
        except ValueError:
            baris = None
    if baris is None:  # halaman publik (login) → pakai organisasi pertama
        baris = db.execute(select(AppSetting).order_by(AppSetting.created_at)).scalars().first()

    if baris is None:
        return Response(status_code=404)

    isi = baris.app_logo if jenis == "aplikasi" else baris.company_logo
    mime = baris.app_logo_mime if jenis == "aplikasi" else baris.company_logo_mime
    if not isi:
        return Response(status_code=404)
    return Response(
        content=bytes(isi),
        media_type=mime or "image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
