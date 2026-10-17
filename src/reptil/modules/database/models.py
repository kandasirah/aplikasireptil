"""Model Manajemen Database: riwayat pekerjaan (job) reset & pembuatan data demo.

Job disimpan di database supaya progres bisa dipantau dari halaman web dan
riwayatnya tetap ada (siapa, kapan, parameter apa, berapa lama, hasilnya apa) —
pola yang sama nanti dipakai modul Integration untuk sinkronisasi eksternal.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

JENIS_JOB = ("demo", "reset")
LABEL_JENIS = {"demo": "Buat data demo", "reset": "Hapus/reset data"}

STATUS_JOB = ("menunggu", "berjalan", "selesai", "gagal")
LABEL_STATUS = {
    "menunggu": "Menunggu",
    "berjalan": "Berjalan",
    "selesai": "Selesai",
    "gagal": "Gagal",
}


class DataJob(UUIDPk, TimestampMixin, Base):
    """Satu pekerjaan pengelolaan data (reset atau generate demo) beserta progresnya."""

    __tablename__ = "data_jobs"
    __table_args__ = (
        CheckConstraint("jenis IN ('demo','reset')", name="jenis_valid"),
        CheckConstraint("status IN ('menunggu','berjalan','selesai','gagal')", name="status_valid"),
        CheckConstraint("persen >= 0 AND persen <= 100", name="persen_valid"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="menunggu")
    tahap: Mapped[str | None] = mapped_column(String(150))
    persen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parameter: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    hasil: Mapped[dict | None] = mapped_column(JSONB)
    pesan: Mapped[str | None] = mapped_column(Text)
    mulai_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selesai_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
