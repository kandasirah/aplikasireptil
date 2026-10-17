"""Service pengaturan: baca/tulis profil aplikasi & perusahaan, termasuk logo."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from reptil.core.config import get_settings
from reptil.core.errors import BusinessRuleError
from reptil.modules.pengaturan.models import AppSetting

# Batasan unggah logo
MAKS_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
MAKS_DIMENSI_LOGO = 1000  # px sisi terpanjang pada berkas yang disimpan
MIME_APP_LOGO = ("image/png", "image/jpeg", "image/webp")
MIME_COMPANY_LOGO = ("image/png", "image/jpeg")  # agar bisa disematkan ke PDF


@dataclass
class Profil:
    """Bentuk siap-pakai untuk template & PDF (tidak butuh akses DB lagi)."""

    app_name: str = "REPTIL"
    app_tagline: str = "Reliable Systems. Connected Business."
    app_logo_url: str | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_npwp: str | None = None
    company_logo_url: str | None = None
    invoice_note: str | None = None
    invoice_terms: str | None = None
    # Dipakai PDF (bytea mentah)
    company_logo: bytes | None = field(default=None, repr=False)
    company_logo_mime: str | None = None

    @property
    def perusahaan(self) -> str:
        return self.company_name or self.app_name


def _url_logo(jenis: str, baris: AppSetting, kolom: bytes | None) -> str | None:
    if not kolom:
        return None
    versi = int((baris.updated_at or datetime.now()).timestamp())
    return f"/logo/{jenis}?v={versi}"


def ke_profil(baris: AppSetting | None) -> Profil:
    """Ubah baris pengaturan menjadi Profil; None → nilai bawaan dari konfigurasi."""
    bawaan = get_settings()
    if baris is None:
        return Profil(app_name=bawaan.app_name)
    return Profil(
        app_name=baris.app_name or bawaan.app_name,
        app_tagline=baris.app_tagline or "Reliable Systems. Connected Business.",
        app_logo_url=_url_logo("aplikasi", baris, baris.app_logo),
        company_name=baris.company_name,
        company_address=baris.company_address,
        company_phone=baris.company_phone,
        company_email=baris.company_email,
        company_npwp=baris.company_npwp,
        company_logo_url=_url_logo("perusahaan", baris, baris.company_logo),
        invoice_note=baris.invoice_note,
        invoice_terms=baris.invoice_terms,
        company_logo=baris.company_logo,
        company_logo_mime=baris.company_logo_mime,
    )


def baris_pengaturan(db: Session, organisation_id: uuid.UUID) -> AppSetting | None:
    return db.execute(
        select(AppSetting).where(AppSetting.organisation_id == organisation_id)
    ).scalar_one_or_none()


def profil_organisasi(db: Session, organisation_id: uuid.UUID | None) -> Profil:
    """Profil untuk organisasi tertentu; bila belum ada, pakai nilai bawaan."""
    if organisation_id is None:
        return Profil(app_name=get_settings().app_name)
    return ke_profil(baris_pengaturan(db, organisation_id))


def profil_publik(db: Session) -> Profil:
    """Profil untuk halaman sebelum login (pakai pengaturan organisasi pertama)."""
    baris = db.execute(select(AppSetting).order_by(AppSetting.created_at)).scalars().first()
    return ke_profil(baris)


def simpan_pengaturan(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data: dict,
    app_logo: tuple[bytes, str, str] | None = None,
    company_logo: tuple[bytes, str, str] | None = None,
    hapus_app_logo: bool = False,
    hapus_company_logo: bool = False,
    rev: str | None = None,
) -> AppSetting:
    """Simpan profil; buat baris baru bila belum ada.

    Hanya field yang benar-benar dikirim yang diperbarui, sehingga pemanggil
    (mis. API atau unggah logo saja) tidak menghapus data lain tanpa sengaja.

    ``rev`` (revisi ``updated_at`` yang dirender di form) dipakai sebagai kunci
    optimistis: form lama yang disimpan setelah data berubah di tempat lain
    ditolak, agar nilai lama tidak menimpa nilai baru tanpa disadari.
    """
    baris = baris_pengaturan(db, organisation_id)
    if baris is None:
        baris = AppSetting(organisation_id=organisation_id, app_name="REPTIL")
        db.add(baris)
    elif rev and baris.updated_at is not None and rev != baris.updated_at.isoformat():
        raise BusinessRuleError(
            "Pengaturan sudah berubah di tab atau jendela lain. "
            "Muat ulang halaman ini, lalu simpan kembali perubahan Anda."
        )

    if "app_name" in data:
        app_name = (data.get("app_name") or "").strip()
        if not app_name:
            raise BusinessRuleError("Nama aplikasi wajib diisi.")
        baris.app_name = app_name

    # field teks: hadir di form = diperbarui (kosong berarti dikosongkan)
    for kunci, kolom in (
        ("app_tagline", "app_tagline"),
        ("company_name", "company_name"),
        ("company_address", "company_address"),
        ("company_phone", "company_phone"),
        ("company_email", "company_email"),
        ("company_npwp", "company_npwp"),
        ("invoice_note", "invoice_note"),
        ("invoice_terms", "invoice_terms"),
    ):
        if kunci in data:
            setattr(baris, kolom, (data.get(kunci) or "").strip() or None)

    if hapus_app_logo:
        baris.app_logo = baris.app_logo_mime = baris.app_logo_name = None
    if app_logo is not None:
        isi, mime, nama = app_logo
        isi, mime = _rapikan_logo(isi, mime, MIME_APP_LOGO, "Logo aplikasi")
        baris.app_logo, baris.app_logo_mime, baris.app_logo_name = isi, mime, nama

    if hapus_company_logo:
        baris.company_logo = baris.company_logo_mime = baris.company_logo_name = None
    if company_logo is not None:
        isi, mime, nama = company_logo
        isi, mime = _rapikan_logo(isi, mime, MIME_COMPANY_LOGO, "Logo perusahaan")
        baris.company_logo, baris.company_logo_mime, baris.company_logo_name = isi, mime, nama

    baris.updated_by = user_id
    db.add(baris)
    db.commit()
    db.refresh(baris)
    return baris


def _validasi_logo(isi: bytes, mime: str, diizinkan: tuple[str, ...], label: str) -> None:
    if mime not in diizinkan:
        raise BusinessRuleError(
            f"{label}: format {mime or 'tidak dikenal'} tidak didukung. "
            f"Gunakan {' atau '.join(diizinkan)}."
        )
    if len(isi) > MAKS_LOGO_BYTES:
        raise BusinessRuleError(
            f"{label} terlalu besar ({len(isi) // 1024} KB). Maksimal {MAKS_LOGO_BYTES // 1024 // 1024} MB."
        )
    if not isi:
        raise BusinessRuleError(f"{label}: berkas kosong.")


def _punya_transparansi(im) -> bool:  # noqa: ANN001 — objek PIL.Image
    if im.mode in ("RGBA", "LA"):
        return True
    return im.mode == "P" and "transparency" in im.info


def _rapikan_logo(
    isi: bytes, mime: str, diizinkan: tuple[str, ...], label: str
) -> tuple[bytes, str]:
    """Validasi, kecilkan, dan kompres logo.

    Selain memeriksa MIME yang dilaporkan klien, isi berkas benar-benar dibaca
    sebagai gambar (agar berkas teks ber-MIME ``image/png`` tetap ditolak) dan
    sisi terpanjang dibatasi ``MAKS_DIMENSI_LOGO`` supaya database serta PDF
    faktur tidak membengkak. Bila Pillow tidak tersedia, berkas dipakai apa adanya.
    """
    _validasi_logo(isi, mime, diizinkan, label)

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — Pillow selalu terpasang di produksi
        return isi, mime

    try:
        with Image.open(BytesIO(isi)) as gambar:
            gambar.load()
            format_asal = (gambar.format or "").upper()
            alfa = _punya_transparansi(gambar)
            perlu_perkecil = max(gambar.size) > MAKS_DIMENSI_LOGO
            if perlu_perkecil:
                gambar.thumbnail((MAKS_DIMENSI_LOGO, MAKS_DIMENSI_LOGO), Image.LANCZOS)

            keluaran = BytesIO()
            if alfa or format_asal == "PNG":
                gambar.convert("RGBA" if alfa else "RGB").save(
                    keluaran, format="PNG", optimize=True
                )
                mime_baru = "image/png"
            elif format_asal == "WEBP" and "image/webp" in diizinkan:
                gambar.convert("RGB").save(keluaran, format="WEBP", quality=88, method=6)
                mime_baru = "image/webp"
            else:
                gambar.convert("RGB").save(
                    keluaran, format="JPEG", quality=88, optimize=True, progressive=True
                )
                mime_baru = "image/jpeg"
    except BusinessRuleError:
        raise
    except Exception as exc:  # noqa: BLE001 — berkas rusak / format tak terbaca
        raise BusinessRuleError(
            f"{label}: berkas tidak dapat dibaca sebagai gambar ({exc.__class__.__name__})."
        ) from exc

    hasil = keluaran.getvalue()
    # Bila tanpa pengecilan dan hasil justru membesar, pakai berkas asli saja
    if not perlu_perkecil and len(hasil) >= len(isi):
        return isi, mime
    return hasil, mime_baru
