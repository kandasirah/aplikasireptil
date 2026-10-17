"""Model pengaturan aplikasi & profil perusahaan (per organisasi)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from reptil.core.metadata import Base, TimestampMixin, UUIDPk


class AppSetting(UUIDPk, TimestampMixin, Base):
    """Profil yang dipakai seluruh antarmuka & faktur.

    Satu baris per organisasi (multi-cabang: tiap perusahaan punya identitas sendiri).
    Logo disimpan sebagai bytea di database agar ikut ter-backup bersama data.
    """

    __tablename__ = "app_settings"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Identitas aplikasi (tampil di sidebar, judul halaman, halaman login)
    app_name: Mapped[str] = mapped_column(String(80), nullable=False, default="REPTIL")
    app_tagline: Mapped[str | None] = mapped_column(String(160))
    app_logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    app_logo_mime: Mapped[str | None] = mapped_column(String(60))
    app_logo_name: Mapped[str | None] = mapped_column(String(160))

    # Identitas perusahaan (tampil di kop faktur & footer)
    company_name: Mapped[str | None] = mapped_column(String(200))
    company_address: Mapped[str | None] = mapped_column(Text)
    company_phone: Mapped[str | None] = mapped_column(String(60))
    company_email: Mapped[str | None] = mapped_column(String(160))
    company_npwp: Mapped[str | None] = mapped_column(String(40))
    company_logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    company_logo_mime: Mapped[str | None] = mapped_column(String(60))
    company_logo_name: Mapped[str | None] = mapped_column(String(160))

    # Konfigurasi faktur
    invoice_note: Mapped[str | None] = mapped_column(Text)
    invoice_terms: Mapped[str | None] = mapped_column(Text)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
