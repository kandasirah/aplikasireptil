"""Helper halaman web REPTIL — konteks template, autentikasi halaman, pesan flash."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from reptil.core.config import get_settings
from reptil.core.security import TOKEN_COOKIE_NAME, decode_access_token
from reptil.core.sysinfo import info_sistem
from reptil.modules.identity.models import User
from reptil.modules.identity.service import get_user_with_relations, permission_codes, role_names
from reptil.modules.pengaturan.service import Profil, profil_organisasi, profil_publik
from reptil.web.templating import templates


def page_user(request: Request, db: Session) -> User | None:
    """Pengguna untuk halaman HTML; None bila belum login / token tidak valid.

    Profil aplikasi & perusahaan ditempelkan ke atribut `profil` agar seluruh
    halaman tidak perlu query tambahan.
    """
    token = request.cookies.get(TOKEN_COOKIE_NAME)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError:
        return None
    user = get_user_with_relations(db, user_id)
    if user is None or not user.is_active:
        return None
    if not getattr(user, "profil", None):
        user.profil = profil_organisasi(db, user.organisation_id)
    return user


def redirect_login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def flash_ok(url: str, pesan: str) -> RedirectResponse:
    return RedirectResponse(f"{url}{'&' if '?' in url else '?'}msg={quote(pesan)}", status_code=303)


def flash_err(url: str, pesan: str) -> RedirectResponse:
    return RedirectResponse(f"{url}{'&' if '?' in url else '?'}err={quote(pesan)}", status_code=303)


def has(user: User, code: str) -> bool:
    kode = permission_codes(user)
    return "*" in kode or code in kode


def context(request: Request, user: User, active: str = "", **extra) -> dict:
    """Konteks standar semua halaman (profil, info sistem, pesan flash)."""
    profil: Profil = getattr(user, "profil", None) or Profil()
    ctx = {
        "app_name": profil.app_name,
        "profil": profil,
        "sistem": info_sistem(profil.app_name),
        "user": user,
        "org": user.organisation,
        "roles": role_names(user),
        "izin": permission_codes(user),
        "is_superadmin": has(user, "*"),
        "active": active,
        "msg": request.query_params.get("msg"),
        "err": request.query_params.get("err"),
    }
    ctx.update(extra)
    return ctx


def context_publik(request: Request, db: Session, **extra) -> dict:
    """Konteks untuk halaman sebelum login (login page)."""
    profil = profil_publik(db)
    ctx = {
        "app_name": profil.app_name,
        "profil": profil,
        "sistem": info_sistem(profil.app_name),
        "msg": request.query_params.get("msg"),
        "err": request.query_params.get("err"),
    }
    ctx.update(extra)
    return ctx


def render(request: Request, template: str, user: User, active: str = "", **extra) -> HTMLResponse:
    return templates.TemplateResponse(request, template, context(request, user, active, **extra))


__all__ = [
    "context",
    "context_publik",
    "flash_err",
    "flash_ok",
    "get_settings",
    "has",
    "page_user",
    "redirect_login",
    "render",
]
