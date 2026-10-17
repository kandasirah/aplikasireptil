"""Service modul identity — autentikasi & pengambilan pengguna."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reptil.core.security import TOKEN_COOKIE_NAME, create_access_token, verify_password
from reptil.modules.identity.models import Organisation, User


class AuthError(Exception):
    """Kredensial salah, akun nonaktif, atau organisasi tidak jelas."""


def get_user_with_relations(db: Session, user_id: uuid.UUID) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles), selectinload(User.organisation))
        .where(User.id == user_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def authenticate(db: Session, email: str, password: str) -> User:
    """Verifikasi kredensial dan kembalikan User yang siap dipakai.

    Email bersifat unik global, jadi organisasi otomatis mengikuti akun.
    """
    stmt = (
        select(User)
        .options(selectinload(User.roles), selectinload(User.organisation))
        .where(User.email == email.strip().lower())
    )
    user = db.execute(stmt).scalar_one_or_none()

    if user is None:
        raise AuthError("Email atau password salah.")
    if not user.is_active:
        raise AuthError("Akun Anda tidak aktif. Hubungi administrator.")
    if not user.organisation.is_active:
        raise AuthError("Organisasi Anda tidak aktif.")
    if not verify_password(password, user.password_hash):
        raise AuthError("Email atau password salah.")

    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def issue_token(db: Session, user: User) -> str:
    return create_access_token(user_id=user.id, organisation_id=user.organisation_id)


def role_names(user: User) -> list[str]:
    return sorted(role.name for role in user.roles)


def permission_codes(user: User) -> set[str]:
    """Gabungan izin dari semua role; `*` berarti superadmin."""
    codes: set[str] = set()
    for role in user.roles:
        codes.update(role.permissions or [])
    return codes


def has_permission(user: User, code: str) -> bool:
    codes = permission_codes(user)
    return "*" in codes or code in codes


__all__ = [
    "AuthError",
    "TOKEN_COOKIE_NAME",
    "authenticate",
    "get_user_with_relations",
    "has_permission",
    "issue_token",
    "permission_codes",
    "role_names",
]
