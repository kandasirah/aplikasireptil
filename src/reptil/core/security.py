"""Helper keamanan REPTIL — hash password (bcrypt) + JWT (PyJWT)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from reptil.core.config import get_settings

ALGORITHM = "HS256"
TOKEN_COOKIE_NAME = "reptil_token"


# ---------------------------------------------------------------- password
def hash_password(plain: str) -> str:
    """Hash plaintext → string bcrypt siap simpan."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Aman terhadap hash kosong/tidak valid (return False, tidak raise)."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# -------------------------------------------------------------------- jwt
def create_access_token(
    *,
    user_id: uuid.UUID,
    organisation_id: uuid.UUID,
    expires_minutes: int | None = None,
) -> str:
    """Buat JWT akses berisi sub (user), org, dan waktu kedaluwarsa."""
    settings = get_settings()
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organisation_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Dekode & validasi JWT. Return None bila tidak valid/kedaluwarsa."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
