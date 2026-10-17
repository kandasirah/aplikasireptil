"""Service RBAC — kelola pengguna (user) & peran (role) beserta izinnya.

Semua fungsi bekerja dalam lingkup satu organisasi (multi-cabang): data
pengguna/peran organisasi lain tidak pernah tersentuh. Email tetap unik global
(sesuai login tanpa kode organisasi), jadi bentrok email dicek ke seluruh tabel.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.security import hash_password
from reptil.modules.identity.models import Role, User, user_roles
from reptil.modules.identity.permissions import WILDCARD, normalisasi

PANJANG_PASSWORD_MINIMAL = 8


# ------------------------------------------------------------------ helper
def _ke_bool(nilai: object) -> bool:
    """Konversi nilai form (checkbox) menjadi bool dengan aman."""
    if isinstance(nilai, bool):
        return nilai
    return str(nilai or "").strip().lower() not in ("", "0", "false", "off", "no")


def _commit(db: Session, pesan_bentrok: str) -> None:
    """Commit; ubah pelanggaran unique menjadi BusinessRuleError yang ramah."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessRuleError(pesan_bentrok) from exc


def _parse_uuid(nilai: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(nilai))
    except (TypeError, ValueError, AttributeError):
        return None


# ------------------------------------------------------------------ peran
@dataclass
class RingkasPeran:
    """Baris peran siap tampil di daftar (dengan hitungan)."""

    role: Role
    jumlah_pengguna: int
    akses_penuh: bool

    @property
    def jumlah_izin(self) -> int:
        return len(self.role.permissions or [])


def list_roles(db: Session, organisation_id: uuid.UUID) -> list[Role]:
    stmt = (
        select(Role)
        .where(Role.organisation_id == organisation_id)
        .order_by(Role.name)
    )
    return list(db.execute(stmt).scalars().all())


def daftar_peran(db: Session, organisation_id: uuid.UUID) -> list[RingkasPeran]:
    stmt = (
        select(Role, func.count(user_roles.c.user_id))
        .outerjoin(user_roles, user_roles.c.role_id == Role.id)
        .where(Role.organisation_id == organisation_id)
        .group_by(Role.id)
        .order_by(Role.name)
    )
    hasil: list[RingkasPeran] = []
    for role, jumlah in db.execute(stmt).all():
        izin = role.permissions or []
        hasil.append(RingkasPeran(role, int(jumlah), WILDCARD in izin))
    return hasil


def get_role(db: Session, organisation_id: uuid.UUID, role_id: uuid.UUID) -> Role:
    stmt = select(Role).where(Role.id == role_id, Role.organisation_id == organisation_id)
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Peran tidak ditemukan.")
    return obj


def simpan_peran(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    data: dict,
    permissions: list[str],
    role_id: uuid.UUID | None = None,
) -> Role:
    """Simpan peran baru atau ubah peran yang ada.

    Bila ``akses_penuh`` dicentang, izin disimpan sebagai ``["*"]`` (superadmin).
    Selain itu, hanya kode izin yang ada di katalog yang dipakai.
    """
    nama = (data.get("name") or "").strip()
    if not nama:
        raise BusinessRuleError("Nama peran wajib diisi.")

    akses_penuh = _ke_bool(data.get("akses_penuh"))
    if akses_penuh:
        izin = [WILDCARD]
    else:
        izin = normalisasi(permissions)
        if not izin:
            raise BusinessRuleError(
                "Pilih minimal satu izin, atau centang 'Akses penuh'."
            )

    obj = (
        get_role(db, organisation_id, role_id)
        if role_id
        else Role(organisation_id=organisation_id)
    )
    obj.name = nama
    obj.description = (data.get("description") or "").strip() or None
    obj.permissions = izin

    db.add(obj)
    _commit(db, f"Nama peran '{nama}' sudah dipakai.")
    db.refresh(obj)
    return obj


def hapus_peran(db: Session, organisation_id: uuid.UUID, role_id: uuid.UUID) -> None:
    """Hapus peran; ditolak bila masih dipakai pengguna mana pun."""
    role = get_role(db, organisation_id, role_id)
    jumlah = db.execute(
        select(func.count())
        .select_from(user_roles)
        .where(user_roles.c.role_id == role.id)
    ).scalar_one()
    if jumlah:
        raise BusinessRuleError(
            f"Peran '{role.name}' masih dipakai {jumlah} pengguna. "
            "Pindahkan pengguna tersebut ke peran lain sebelum menghapus."
        )
    db.delete(role)
    db.commit()


# --------------------------------------------------------------- pengguna
def list_users(
    db: Session,
    organisation_id: uuid.UUID,
    *,
    q: str = "",
    aktif: bool | None = None,
) -> list[User]:
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.organisation_id == organisation_id)
    )
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(User.full_name.ilike(like) | User.email.ilike(like))
    if aktif is not None:
        stmt = stmt.where(User.is_active.is_(aktif))
    stmt = stmt.order_by(User.is_active.desc(), User.full_name)
    return list(db.execute(stmt).scalars().all())


def get_user(db: Session, organisation_id: uuid.UUID, user_id: uuid.UUID) -> User:
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id, User.organisation_id == organisation_id)
    )
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Pengguna tidak ditemukan.")
    return obj


def _roles_terpilih(
    db: Session, organisation_id: uuid.UUID, role_ids: list[str]
) -> list[Role]:
    ids = {_parse_uuid(r) for r in (role_ids or [])}
    ids.discard(None)
    if not ids:
        return []
    roles = list(
        db.execute(
            select(Role).where(
                Role.organisation_id == organisation_id, Role.id.in_(ids)
            )
        ).scalars().all()
    )
    if len(roles) != len(ids):
        raise BusinessRuleError("Ada peran yang dipilih tidak valid untuk organisasi ini.")
    return roles


def simpan_user(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    data: dict,
    role_ids: list[str],
    user_id: uuid.UUID | None = None,
    aktor_id: uuid.UUID | None = None,
) -> User:
    """Simpan pengguna baru atau ubah pengguna yang ada.

    Kata sandi wajib saat membuat akun; saat mengubah boleh dikosongkan
    (berarti tidak diubah). Pengguna tidak boleh menonaktifkan akunnya sendiri.
    """
    email = (data.get("email") or "").strip().lower()
    nama = (data.get("full_name") or "").strip()
    if not email:
        raise BusinessRuleError("Email wajib diisi.")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise BusinessRuleError("Format email tidak valid.")
    if not nama:
        raise BusinessRuleError("Nama lengkap wajib diisi.")

    aktif_baru = _ke_bool(data.get("is_active"))
    if user_id is not None and aktor_id is not None and user_id == aktor_id and not aktif_baru:
        raise BusinessRuleError("Anda tidak dapat menonaktifkan akun Anda sendiri.")

    obj = (
        get_user(db, organisation_id, user_id)
        if user_id
        else User(organisation_id=organisation_id)
    )
    peran_baru = _roles_terpilih(db, organisation_id, role_ids)
    if user_id is not None and aktor_id is not None and user_id == aktor_id:
        # Cegah admin mengunci diri sendiri dengan melepas akses penuhnya.
        lama_penuh = any(WILDCARD in (r.permissions or []) for r in obj.roles)
        baru_penuh = any(WILDCARD in (r.permissions or []) for r in peran_baru)
        if lama_penuh and not baru_penuh:
            raise BusinessRuleError(
                "Anda tidak dapat menghapus akses penuh dari akun Anda sendiri."
            )

    obj.email = email
    obj.full_name = nama
    obj.is_active = aktif_baru
    obj.roles = peran_baru

    # Kata sandi: wajib saat membuat akun; saat mengubah cukup bila diisi.
    password = (data.get("password") or "").strip()
    if user_id is None or password:
        if len(password) < PANJANG_PASSWORD_MINIMAL:
            raise BusinessRuleError(
                f"Kata sandi minimal {PANJANG_PASSWORD_MINIMAL} karakter."
            )
        obj.password_hash = hash_password(password)

    db.add(obj)
    _commit(db, f"Email '{email}' sudah dipakai akun lain.")
    db.refresh(obj)
    return obj


def izin_efektif(user: User) -> list[str]:
    """Gabungan kode izin dari semua peran pengguna (urut, tanpa duplikat)."""
    kode: set[str] = set()
    for role in user.roles:
        kode.update(role.permissions or [])
    return sorted(kode)


__all__ = [
    "PANJANG_PASSWORD_MINIMAL",
    "RingkasPeran",
    "daftar_peran",
    "get_role",
    "get_user",
    "hapus_peran",
    "izin_efektif",
    "list_roles",
    "list_users",
    "simpan_peran",
    "simpan_user",
]
