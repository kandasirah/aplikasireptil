"""Model finance REPTIL: bagan akun, jurnal umum, dan pembayaran (AP/AR).

Alur uang yang dimodelkan:

    faktur pembelian  → Dr Persediaan   / Cr Utang Usaha      (utang bertambah)
    faktur penjualan  → Dr Piutang      / Cr Penjualan        (piutang bertambah)
                        Dr HPP          / Cr Persediaan       (harga pokok)
    pembayaran keluar → Dr Utang Usaha  / Cr Kas & Bank
    pembayaran masuk  → Dr Kas & Bank   / Cr Piutang Usaha

Saldo utang/piutang faktur **tidak** disimpan sebagai kolom yang di-update, tetapi
diagregasi dari alokasi pembayaran (`payment_allocations`) — pola yang sama dengan
kartu stok: satu sumber kebenaran, tidak ada nilai yang bisa "hilang" karena race.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reptil.core.metadata import Base, TimestampMixin, UUIDPk

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
# Sisi bertambahnya saldo: aset & beban di debit, sisanya di kredit
NORMAL_DEBIT = {"asset", "expense"}

JOURNAL_SOURCES = ("faktur_beli", "faktur_jual", "pembayaran", "manual")
JOURNAL_STATUSES = ("posted", "void")

PAYMENT_DIRECTIONS = ("masuk", "keluar")
PAYMENT_METHODS = ("transfer", "tunai", "cek", "lainnya")

# Kode akun baku yang dipakai penjurnalan otomatis
AKUN_KAS = "1-100"
AKUN_PIUTANG = "1-200"
AKUN_PERSEDIAAN = "1-300"
AKUN_UTANG = "2-100"
AKUN_MODAL = "3-100"
AKUN_PENJUALAN = "4-100"
AKUN_HPP = "5-100"
AKUN_BEBAN_LAIN = "5-900"

# Bagan akun bawaan untuk organisasi baru
COA_BAWAAN: tuple[tuple[str, str, str], ...] = (
    (AKUN_KAS, "Kas & Bank", "asset"),
    (AKUN_PIUTANG, "Piutang Usaha", "asset"),
    (AKUN_PERSEDIAAN, "Persediaan Barang", "asset"),
    (AKUN_UTANG, "Utang Usaha", "liability"),
    (AKUN_MODAL, "Modal Pemilik", "equity"),
    (AKUN_PENJUALAN, "Penjualan", "revenue"),
    (AKUN_HPP, "Harga Pokok Penjualan", "expense"),
    (AKUN_BEBAN_LAIN, "Beban Lain-lain", "expense"),
)


class Account(UUIDPk, TimestampMixin, Base):
    """Bagan akun (Chart of Accounts)."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("organisation_id", "kode", name="uq_accounts_org_kode"),
        CheckConstraint(
            "tipe IN ('asset','liability','equity','revenue','expense')", name="tipe_valid"
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kode: Mapped[str] = mapped_column(String(20), nullable=False)
    nama: Mapped[str] = mapped_column(String(120), nullable=False)
    tipe: Mapped[str] = mapped_column(String(12), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def saldo_normal(self) -> str:
        return "debit" if self.tipe in NORMAL_DEBIT else "kredit"


class JournalEntry(UUIDPk, TimestampMixin, Base):
    """Satu jurnal (selalu berpasangan debit–kredit, total harus seimbang)."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_journal_entries_org_number"),
        CheckConstraint(
            "sumber IN ('faktur_beli','faktur_jual','pembayaran','manual')",
            name="sumber_valid",
        ),
        CheckConstraint("status IN ('posted','void')", name="status_valid"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    memo: Mapped[str | None] = mapped_column(Text)
    sumber: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="posted")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="JournalLine.line_no",
    )


class JournalLine(UUIDPk, Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="nilai_tidak_negatif"),
        CheckConstraint("debit = 0 OR credit = 0", name="hanya_satu_sisi"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="SET NULL")
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    memo: Mapped[str | None] = mapped_column(String(200))

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account = relationship("Account", lazy="joined")
    partner = relationship("Partner", lazy="joined")


class Payment(UUIDPk, TimestampMixin, Base):
    """Pembayaran utang (keluar) atau penerimaan piutang (masuk)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("organisation_id", "number", name="uq_payments_org_number"),
        CheckConstraint("arah IN ('masuk','keluar')", name="arah_valid"),
        CheckConstraint("metode IN ('transfer','tunai','cek','lainnya')", name="metode_valid"),
        CheckConstraint("jumlah > 0", name="jumlah_positif"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    arah: Mapped[str] = mapped_column(String(6), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    akun_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    jumlah: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    metode: Mapped[str] = mapped_column(String(15), nullable=False, default="transfer")
    referensi: Mapped[str | None] = mapped_column(String(60))
    catatan: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    partner = relationship("Partner", lazy="joined")
    akun = relationship("Account", lazy="joined")
    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )


class PaymentAllocation(UUIDPk, Base):
    """Bagian pembayaran yang memelunasi satu faktur (pembelian atau penjualan)."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("jumlah > 0", name="jumlah_positif"),
        CheckConstraint(
            "(purchase_invoice_id IS NOT NULL) <> (sales_invoice_id IS NOT NULL)",
            name="tepat_satu_faktur",
        ),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="CASCADE"), index=True
    )
    sales_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), index=True
    )
    jumlah: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    purchase_invoice = relationship("PurchaseInvoice", lazy="joined")
    sales_invoice = relationship("SalesInvoice", lazy="joined")

    @property
    def nomor_faktur(self) -> str | None:
        if self.purchase_invoice is not None:
            return self.purchase_invoice.number
        if self.sales_invoice is not None:
            return self.sales_invoice.number
        return None
