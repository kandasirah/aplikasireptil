"""API JSON keuangan: bagan akun, jurnal, pembayaran, utang & piutang (Swagger)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from reptil.api.common import BATAS_BAWAAN, Halaman, SkemaIn, SkemaOut, halaman
from reptil.core.db import get_db
from reptil.modules.finance import service as svc
from reptil.modules.identity.deps import require_permission
from reptil.modules.identity.models import User

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])

BACA = require_permission("finance.read")
TULIS = require_permission("finance.write")


# --------------------------------------------------------------- bagan akun
class AccountIn(SkemaIn):
    kode: str = Field(min_length=1, examples=["1-100"])
    nama: str = Field(min_length=1, examples=["Kas"])
    tipe: str = Field(description="asset | liability | equity | revenue | expense")


class AccountUpdateIn(SkemaIn):
    nama: str = Field(min_length=1)
    aktif: bool = True


class AccountOut(SkemaOut):
    id: uuid.UUID
    kode: str
    nama: str
    tipe: str
    aktif: bool


@router.get("/accounts", response_model=Halaman[AccountOut], summary="Daftar akun (COA)")
def list_accounts(
    q: str = Query("", description="Cari kode / nama akun"),
    tipe: str = Query("", description="asset | liability | equity | revenue | expense"),
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_accounts(db, user.organisation_id, q=q, tipe=tipe)
    return halaman(items, limit, offset)


@router.post("/accounts", response_model=AccountOut, status_code=201, summary="Tambah akun")
def create_account(
    payload: AccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.buat_akun(
        db,
        organisation_id=user.organisation_id,
        kode=payload.kode,
        nama=payload.nama,
        tipe=payload.tipe,
    )


@router.get("/cash-accounts", response_model=list[AccountOut], summary="Akun kas & bank")
def cash_accounts(db: Session = Depends(get_db), user: User = Depends(BACA)) -> list:
    return svc.akun_kas(db, user.organisation_id)


@router.get("/accounts/{account_id}", response_model=AccountOut, summary="Detail akun")
def get_account(
    account_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_akun(db, user.organisation_id, account_id)


@router.put("/accounts/{account_id}", response_model=AccountOut, summary="Ubah akun")
def update_account(
    payload: AccountUpdateIn,
    account_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.ubah_akun(
        db,
        organisation_id=user.organisation_id,
        akun_id=account_id,
        nama=payload.nama,
        aktif=payload.aktif,
    )


# ------------------------------------------------------------------ jurnal
class JournalLineOut(SkemaOut):
    id: uuid.UUID
    line_no: int
    account_id: uuid.UUID
    partner_id: uuid.UUID | None
    debit: Decimal
    credit: Decimal
    memo: str | None


class JournalOut(SkemaOut):
    id: uuid.UUID
    number: str
    tanggal: date
    memo: str | None
    sumber: str
    ref_type: str | None
    ref_id: uuid.UUID | None
    status: str
    total: Decimal
    created_at: datetime
    lines: list[JournalLineOut] = Field(default_factory=list)


@router.get("/journal", response_model=Halaman[JournalOut], summary="Daftar jurnal umum")
def list_journal(
    q: str = Query("", description="Cari nomor / memo"),
    sumber: str = Query("", description="manual | purchase_invoice | sales_invoice | ..."),
    dari: date | None = None,
    sampai: date | None = None,
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_jurnal(
        db, user.organisation_id, q=q, sumber=sumber, dari=dari, sampai=sampai, batas=100_000
    )
    return halaman(items, limit, offset)


@router.get("/journal/{entry_id}", response_model=JournalOut, summary="Detail jurnal")
def get_journal(
    entry_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_jurnal(db, user.organisation_id, entry_id)


# -------------------------------------------------------------- pembayaran
class PaymentIn(SkemaIn):
    arah: str = Field(description="masuk (piutang) | keluar (utang)")
    faktur_id: uuid.UUID
    akun_id: uuid.UUID | None = Field(default=None, description="Akun kas/bank; kosong = bawaan")
    jumlah: Decimal = Field(gt=0)
    tanggal: date
    metode: str = Field(default="transfer", description="transfer | tunai | cek | lainnya")
    referensi: str | None = None
    catatan: str | None = None


class PaymentOut(SkemaOut):
    id: uuid.UUID
    number: str
    arah: str
    tanggal: date
    partner_id: uuid.UUID
    akun_id: uuid.UUID
    jumlah: Decimal
    metode: str
    referensi: str | None
    catatan: str | None
    created_at: datetime


class RiwayatBayarOut(SkemaOut):
    payment: PaymentOut
    jumlah: Decimal


@router.get("/payments", response_model=Halaman[PaymentOut], summary="Daftar pembayaran")
def list_payments(
    arah: str = Query("", description="masuk | keluar"),
    q: str = Query("", description="Cari nomor / referensi"),
    dari: date | None = None,
    sampai: date | None = None,
    limit: int = BATAS_BAWAAN,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> dict:
    items = svc.list_pembayaran(
        db, user.organisation_id, arah=arah, q=q, dari=dari, sampai=sampai, batas=100_000
    )
    return halaman(items, limit, offset)


@router.post("/payments", response_model=PaymentOut, status_code=201, summary="Catat pembayaran")
def create_payment(
    payload: PaymentIn,
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> object:
    return svc.catat_pembayaran(
        db,
        organisation_id=user.organisation_id,
        user_id=user.id,
        arah=payload.arah,
        faktur_id=payload.faktur_id,
        akun_id=payload.akun_id or svc.akun_kas_default(db, user.organisation_id).id,
        jumlah=payload.jumlah,
        tanggal=payload.tanggal,
        metode=payload.metode,
        referensi=payload.referensi,
        catatan=payload.catatan,
    )


@router.get("/payments/{payment_id}", response_model=PaymentOut, summary="Detail pembayaran")
def get_payment(
    payment_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> object:
    return svc.get_pembayaran(db, user.organisation_id, payment_id)


@router.delete(
    "/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Batalkan pembayaran",
)
def delete_payment(
    payment_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    user: User = Depends(TULIS),
) -> Response:
    svc.hapus_pembayaran(db, organisation_id=user.organisation_id, payment_id=payment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/invoices/{faktur_id}/payments",
    response_model=list[RiwayatBayarOut],
    summary="Riwayat pembayaran satu faktur",
)
def invoice_payments(
    faktur_id: uuid.UUID = Path(...),
    arah: str = Query("keluar", description="keluar (beli) | masuk (jual)"),
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> list:
    faktur = svc.faktur_untuk_pembayaran(db, user.organisation_id, faktur_id, arah)
    return svc.pembayaran_faktur(db, faktur)


# ------------------------------------------------------------ utang-piutang
class TagihanOut(SkemaOut):
    faktur_id: uuid.UUID
    nomor: str
    partner_id: uuid.UUID
    partner: str
    tanggal: date
    jatuh_tempo: date | None
    umur_hari: int
    kelompok: str
    total: Decimal
    dibayar: Decimal
    sisa: Decimal


def _tagihan(rows: list[dict]) -> list[dict]:
    return [
        {
            "faktur_id": r["faktur"].id,
            "nomor": r["faktur"].number,
            "partner_id": r["partner"].id,
            "partner": r["partner"].nama,
            "tanggal": r["faktur"].tanggal,
            "jatuh_tempo": r["jatuh_tempo"],
            "umur_hari": r["umur"],
            "kelompok": r["kelompok"],
            "total": r["total"],
            "dibayar": r["dibayar"],
            "sisa": r["sisa"],
        }
        for r in rows
    ]


@router.get("/payables", response_model=list[TagihanOut], summary="Daftar utang")
def payables(db: Session = Depends(get_db), user: User = Depends(BACA)) -> list:
    return _tagihan(svc.daftar_utang(db, user.organisation_id))


@router.get("/receivables", response_model=list[TagihanOut], summary="Daftar piutang")
def receivables(db: Session = Depends(get_db), user: User = Depends(BACA)) -> list:
    return _tagihan(svc.daftar_piutang(db, user.organisation_id))


class NeracaOut(SkemaOut):
    kode: str
    nama: str
    tipe: str
    sisi: str
    debit: Decimal
    credit: Decimal
    saldo: Decimal


@router.get("/trial-balance", response_model=list[NeracaOut], summary="Neraca saldo")
def trial_balance(
    dari: date | None = None,
    sampai: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(BACA),
) -> list:
    rows = svc.saldo_akun(db, user.organisation_id, dari=dari, sampai=sampai)
    return [
        {
            "kode": r["akun"].kode,
            "nama": r["akun"].nama,
            "tipe": r["akun"].tipe,
            "sisi": r["sisi"],
            "debit": r["debit"],
            "credit": r["credit"],
            "saldo": r["saldo"],
        }
        for r in rows
    ]


@router.get("/summary", summary="Ringkasan keuangan")
def summary(db: Session = Depends(get_db), user: User = Depends(BACA)) -> dict:
    r = svc.ringkasan(db, user.organisation_id)
    return {
        "total_utang": r["total_utang"],
        "jumlah_faktur_utang": r["jumlah_faktur_utang"],
        "total_piutang": r["total_piutang"],
        "jumlah_faktur_piutang": r["jumlah_faktur_piutang"],
        "utang_jatuh_tempo": r["utang_jatuh_tempo"],
        "piutang_jatuh_tempo": r["piutang_jatuh_tempo"],
        "saldo_kas": r["saldo_kas"],
        "penjualan_bulan_ini": r["penjualan_bulan_ini"],
        "hpp_bulan_ini": r["hpp_bulan_ini"],
        "laba_kotor_bulan_ini": r["laba_kotor_bulan_ini"],
        "pembayaran_terakhir": [
            {
                "id": p.id,
                "number": p.number,
                "arah": p.arah,
                "tanggal": p.tanggal,
                "jumlah": p.jumlah,
                "metode": p.metode,
            }
            for p in r["pembayaran_terakhir"]
        ],
        "aging_utang": r["aging_utang"],
        "aging_piutang": r["aging_piutang"],
    }
