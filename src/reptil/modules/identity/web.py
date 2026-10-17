"""Halaman web RBAC: manajemen pengguna (user) & peran (role) dengan centang izin.

Izin halaman:
    - ``users.read``  / ``users.write``  → /pengguna
    - ``roles.read``  / ``roles.write``  → /peran
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.modules.identity.permissions import (
    KATALOG,
    WILDCARD,
    kode_tidak_dikenal,
    label_dari_kode,
    normalisasi,
    semua_kode,
)
from reptil.modules.identity.rbac import (
    daftar_peran,
    get_role,
    get_user,
    hapus_peran,
    izin_efektif,
    list_roles,
    list_users,
    simpan_peran,
    simpan_user,
)
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-identity"])


def _guard(request: Request, db: Session, izin: str):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


def _label_kode(kode: list[str]) -> list[tuple[str, str]]:
    """[(kode, label)] untuk ditampilkan sebagai daftar izin."""
    return [(k, label_dari_kode(k)) for k in kode]


# ================================================================== pengguna
@router.get("/pengguna", response_class=HTMLResponse, include_in_schema=False)
def pengguna_daftar(request: Request, q: str = "", aktif: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db, "users.read")
    if err:
        return err
    filter_aktif = {"aktif": True, "nonaktif": False}.get(aktif)
    h = halaman(request, list_users(db, user.organisation_id, q=q, aktif=filter_aktif))
    return render(
        request,
        "pengguna/daftar.html",
        user,
        "pengguna",
        pengguna=h.items,
        h=h,
        q=q,
        aktif=aktif,
    )


@router.get("/pengguna/baru", response_class=HTMLResponse, include_in_schema=False)
def pengguna_baru(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "users.write")
    if err:
        return err
    return render(
        request,
        "pengguna/form.html",
        user,
        "pengguna",
        edit_user=None,
        peran=list_roles(db, user.organisation_id),
        izin_user=[],
    )


@router.get("/pengguna/{user_id}/ubah", response_class=HTMLResponse, include_in_schema=False)
def pengguna_ubah(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "users.write")
    if err:
        return err
    try:
        edit_user = get_user(db, user.organisation_id, user_id)
    except NotFoundError as exc:
        return flash_err("/pengguna", str(exc))
    return render(
        request,
        "pengguna/form.html",
        user,
        "pengguna",
        edit_user=edit_user,
        peran=list_roles(db, user.organisation_id),
        izin_user=_label_kode(izin_efektif(edit_user)),
        wildcard=WILDCARD in izin_efektif(edit_user),
    )


@router.post("/pengguna", include_in_schema=False)
async def pengguna_simpan(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "users.write")
    if err:
        return err
    form = await request.form()
    data = {k: form.get(k) for k in ("email", "full_name", "password")}
    data["is_active"] = form.get("is_active") is not None
    try:
        baru = simpan_user(
            db,
            organisation_id=user.organisation_id,
            data=data,
            role_ids=form.getlist("role_ids"),
        )
    except BusinessRuleError as exc:
        return flash_err("/pengguna/baru", str(exc))
    return flash_ok("/pengguna", f"Pengguna {baru.full_name} dibuat.")


@router.post("/pengguna/{user_id}", include_in_schema=False)
async def pengguna_update(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "users.write")
    if err:
        return err
    form = await request.form()
    data = {k: form.get(k) for k in ("email", "full_name", "password")}
    data["is_active"] = form.get("is_active") is not None
    try:
        diubah = simpan_user(
            db,
            organisation_id=user.organisation_id,
            data=data,
            role_ids=form.getlist("role_ids"),
            user_id=user_id,
            aktor_id=user.id,
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/pengguna/{user_id}/ubah", str(exc))
    return flash_ok("/pengguna", f"Pengguna {diubah.full_name} diperbarui.")


# ===================================================================== peran
@router.get("/peran", response_class=HTMLResponse, include_in_schema=False)
def peran_daftar(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.read")
    if err:
        return err
    daftar = daftar_peran(db, user.organisation_id)
    kata = q.strip().lower()
    if kata:
        daftar = [
            r
            for r in daftar
            if kata in r.role.name.lower() or kata in (r.role.description or "").lower()
        ]
    h = halaman(request, daftar)
    return render(
        request,
        "peran/daftar.html",
        user,
        "peran",
        peran=h.items,
        h=h,
        q=q,
    )


@router.get("/peran/baru", response_class=HTMLResponse, include_in_schema=False)
def peran_baru(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.write")
    if err:
        return err
    return render(
        request,
        "peran/form.html",
        user,
        "peran",
        edit_role=None,
        katalog=KATALOG,
        terpilih=set(),
        akses_penuh=False,
        asing=set(),
    )


@router.get("/peran/{role_id}/ubah", response_class=HTMLResponse, include_in_schema=False)
def peran_ubah(role_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.write")
    if err:
        return err
    try:
        role = get_role(db, user.organisation_id, role_id)
    except NotFoundError as exc:
        return flash_err("/peran", str(exc))
    izin = role.permissions or []
    akses_penuh = WILDCARD in izin
    return render(
        request,
        "peran/form.html",
        user,
        "peran",
        edit_role=role,
        katalog=KATALOG,
        terpilih=set(semua_kode()) if akses_penuh else set(normalisasi(izin)),
        akses_penuh=akses_penuh,
        asing=kode_tidak_dikenal(izin),
    )


@router.post("/peran", include_in_schema=False)
async def peran_simpan(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.write")
    if err:
        return err
    form = await request.form()
    try:
        role = simpan_peran(
            db,
            organisation_id=user.organisation_id,
            data={"name": form.get("name"), "description": form.get("description"),
                  "akses_penuh": form.get("akses_penuh")},
            permissions=form.getlist("permissions"),
        )
    except BusinessRuleError as exc:
        return flash_err("/peran/baru", str(exc))
    return flash_ok("/peran", f"Peran {role.name} dibuat.")


@router.post("/peran/{role_id}", include_in_schema=False)
async def peran_update(role_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.write")
    if err:
        return err
    form = await request.form()
    try:
        role = simpan_peran(
            db,
            organisation_id=user.organisation_id,
            data={"name": form.get("name"), "description": form.get("description"),
                  "akses_penuh": form.get("akses_penuh")},
            permissions=form.getlist("permissions"),
            role_id=role_id,
        )
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err(f"/peran/{role_id}/ubah", str(exc))
    return flash_ok("/peran", f"Peran {role.name} diperbarui.")


@router.post("/peran/{role_id}/hapus", include_in_schema=False)
async def peran_hapus(role_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, "roles.write")
    if err:
        return err
    try:
        hapus_peran(db, user.organisation_id, role_id)
    except (BusinessRuleError, NotFoundError) as exc:
        return flash_err("/peran", str(exc))
    return flash_ok("/peran", "Peran dihapus.")


__all__ = ["router"]
