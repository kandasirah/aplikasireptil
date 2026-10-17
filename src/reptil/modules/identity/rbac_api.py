"""API JSON RBAC: pengguna, peran, dan katalog izin (Swagger)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from reptil.api.common import BATAS_BAWAAN, Halaman, SkemaIn, SkemaOut, halaman
from reptil.core.db import get_db
from reptil.modules.identity import rbac
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.identity.permissions import KATALOG

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])

BACA_PENGGUNA = require_permission("users.read")
TULIS_PENGGUNA = require_permission("users.write")
BACA_PERAN = require_permission("roles.read")
TULIS_PERAN = require_permission("roles.write")


# ---------------------------------------------------------------- pengguna
class UserIn(SkemaIn):
    email: str
    full_name: str
    password: str | None = Field(default=None, description="Wajib saat membuat akun")
    is_active: bool | None = None
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class UserOut(SkemaOut):
    id: uuid.UUID
    email: str
    full_name: str
    organisation_id: uuid.UUID
    is_active: bool
    roles: list[str]
    created_at: datetime


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "organisation_id": user.organisation_id,
        "is_active": user.is_active,
        "roles": sorted(role.name for role in user.roles),
        "created_at": user.created_at,
    }


def _data_user(payload: UserIn, *, buat: bool) -> dict:
    data: dict = {
        "email": payload.email,
        "full_name": payload.full_name,
        "password": payload.password,
    }
    if payload.is_active is not None:
        data["is_active"] = payload.is_active
    elif buat:
        data["is_active"] = True
    return data


@router.get("/users", response_model=Halaman[UserOut], summary="Daftar pengguna")
def list_users(
    q: str = Query("", description="Cari email / nama"),
    aktif: bool | None = Query(None, description="Filter status aktif"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA_PENGGUNA),
) -> dict:
    items = rbac.list_users(db, user.organisation_id, q=q, aktif=aktif)
    return halaman([_user_out(u) for u in items], limit, offset)


@router.post("/users", response_model=UserOut, status_code=201, summary="Tambah pengguna")
def create_user(
    payload: UserIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS_PENGGUNA),
) -> dict:
    obj = rbac.simpan_user(
        db,
        organisation_id=user.organisation_id,
        data=_data_user(payload, buat=True),
        role_ids=[str(r) for r in payload.role_ids],
        aktor_id=user.id,
    )
    return _user_out(obj)


@router.get("/users/{user_id}", response_model=UserOut, summary="Detail pengguna")
def get_user(
    user_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA_PENGGUNA),
) -> dict:
    return _user_out(rbac.get_user(db, user.organisation_id, user_id))


@router.put("/users/{user_id}", response_model=UserOut, summary="Ubah pengguna")
def update_user(
    payload: UserIn,
    user_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS_PENGGUNA),
) -> dict:
    obj = rbac.simpan_user(
        db,
        organisation_id=user.organisation_id,
        data=_data_user(payload, buat=False),
        role_ids=[str(r) for r in payload.role_ids],
        user_id=user_id,
        aktor_id=user.id,
    )
    return _user_out(obj)


# -------------------------------------------------------------------- peran
class RoleIn(SkemaIn):
    name: str = Field(min_length=1)
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleOut(SkemaOut):
    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]
    created_at: datetime


@router.get("/roles", response_model=Halaman[RoleOut], summary="Daftar peran")
def list_roles(
    q: str = Query("", description="Cari nama peran"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA_PERAN),
) -> dict:
    items = rbac.list_roles(db, user.organisation_id)
    if q:
        kunci = q.strip().lower()
        items = [r for r in items if kunci in r.name.lower()]
    return halaman(items, limit, offset)


@router.post("/roles", response_model=RoleOut, status_code=201, summary="Tambah peran")
def create_role(
    payload: RoleIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS_PERAN),
) -> object:
    return rbac.simpan_peran(
        db,
        organisation_id=user.organisation_id,
        data={"name": payload.name, "description": payload.description},
        permissions=payload.permissions,
    )


@router.get("/roles/{role_id}", response_model=RoleOut, summary="Detail peran")
def get_role(
    role_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA_PERAN),
) -> object:
    return rbac.get_role(db, user.organisation_id, role_id)


@router.put("/roles/{role_id}", response_model=RoleOut, summary="Ubah peran")
def update_role(
    payload: RoleIn,
    role_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS_PERAN),
) -> object:
    return rbac.simpan_peran(
        db,
        organisation_id=user.organisation_id,
        data={"name": payload.name, "description": payload.description},
        permissions=payload.permissions,
        role_id=role_id,
    )


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus peran",
)
def delete_role(
    role_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS_PERAN),
) -> Response:
    rbac.hapus_peran(db, user.organisation_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ izin (katalog)
class IzinOut(SkemaOut):
    code: str
    label: str


class GrupIzinOut(SkemaOut):
    nama: str
    keterangan: str
    izin: list[IzinOut]


@router.get("/permissions", response_model=list[GrupIzinOut], summary="Katalog izin")
def list_permissions(_user: User = Depends(BACA_PERAN)) -> list:
    return [
        {
            "nama": grup.nama,
            "keterangan": grup.keterangan,
            "izin": [{"code": i.code, "label": i.label} for i in grup.izin],
        }
        for grup in KATALOG
    ]
