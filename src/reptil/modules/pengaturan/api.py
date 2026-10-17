"""API JSON pengaturan: profil aplikasi & identitas perusahaan (Swagger)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reptil.api.common import SkemaIn, SkemaOut
from reptil.core.db import get_db
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User
from reptil.modules.pengaturan.service import profil_organisasi, simpan_pengaturan

router = APIRouter(prefix="/api/v1", tags=["settings"])

BACA = require_permission("settings.read")
TULIS = require_permission("settings.write")


class ProfilOut(SkemaOut):
    app_name: str
    app_tagline: str
    app_logo_url: str | None
    company_name: str | None
    company_address: str | None
    company_phone: str | None
    company_email: str | None
    company_npwp: str | None
    company_logo_url: str | None
    invoice_note: str | None
    invoice_terms: str | None


class SettingsIn(SkemaIn):
    app_name: str | None = None
    app_tagline: str | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_npwp: str | None = None
    invoice_note: str | None = None
    invoice_terms: str | None = None


@router.get("/settings", response_model=ProfilOut, summary="Profil aplikasi & perusahaan")
def get_settings_api(db: Session = Depends(get_db), user: User = Depends(BACA)) -> object:
    return profil_organisasi(db, user.organisation_id)


@router.put("/settings", response_model=ProfilOut, summary="Ubah profil aplikasi & perusahaan")
def update_settings(
    payload: SettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    simpan_pengaturan(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        data=payload.model_dump(exclude_unset=True),
    )
    return profil_organisasi(db, user.organisation_id)
