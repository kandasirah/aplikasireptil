"""API autentikasi (JSON) — dipakai SPA/mitra integrasi."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from reptil.core.config import get_settings
from reptil.core.db import get_db
from reptil.core.security import TOKEN_COOKIE_NAME
from reptil.modules.identity.deps import get_current_user
from reptil.modules.identity.models import User
from reptil.modules.identity.schemas import LoginRequest, TokenResponse, UserOut
from reptil.modules.identity.service import (
    AuthError,
    authenticate,
    issue_token,
    role_names,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        organisation_id=user.organisation_id,
        roles=role_names(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, response: Response, db: Session = Depends(get_db)
) -> TokenResponse:
    try:
        user = authenticate(db, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    token = issue_token(db, user)
    settings = get_settings()
    # Cookie agar halaman web ikut terautentikasi; header Authorization tetap didukung.
    response.set_cookie(
        key=TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=_to_out(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _to_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(TOKEN_COOKIE_NAME, path="/")
