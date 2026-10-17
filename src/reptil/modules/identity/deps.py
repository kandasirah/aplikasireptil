"""Dependency autentikasi & otorisasi (RBAC) yang dipakai endpoint lain."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.security import TOKEN_COOKIE_NAME, decode_access_token
from reptil.modules.identity.models import User
from reptil.modules.identity.service import get_user_with_relations, has_permission

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Belum login atau sesi sudah berakhir.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    """Token diambil dari cookie (halaman web) atau header Bearer (API/mitra)."""
    token = request.cookies.get(TOKEN_COOKIE_NAME)
    if token:
        return token
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise _UNAUTHORIZED

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise _UNAUTHORIZED

    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError:
        raise _UNAUTHORIZED from None

    user = get_user_with_relations(db, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


def require_permission(code: str):
    """Factory dependency: endpoint hanya boleh diakses pemilik izin `code`."""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Anda tidak punya izin '{code}'.",
            )
        return user

    return _guard
