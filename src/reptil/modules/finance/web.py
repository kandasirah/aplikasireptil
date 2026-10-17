"""Halaman web finance: ringkasan, utang/piutang (aging), pembayaran, jurnal, bagan akun."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from reptil.core.db import get_db
from reptil.core.errors import AppError
from reptil.core.parsing import to_date
from reptil.modules.finance import service as fin
from reptil.modules.finance.models import ACCOUNT_TYPES, PAYMENT_METHODS
from reptil.web.common import flash_err, flash_ok, has, page_user, redirect_login, render
from reptil.web.pagination import halaman

router = APIRouter(tags=["web-finance"])


def _guard(request: Request, db: Session, butuh_tulis: bool = False):
    user = page_user(request, db)
    if user is None:
        return None, redirect_login()
    izin = "finance.write" if butuh_tulis else "finance.read"
    if not has(user, izin):
        return None, flash_err("/dashboard", f"Anda tidak punya izin '{izin}'.")
    return user, None


def _tanggal_opsional(teks: str, label: str) -> date | None:
    """Kosong berarti tanpa batas tanggal (bukan error)."""
    return to_date(teks, label, default=None) if (teks or "").strip() else None


def _konteks_finance() -> dict:
    return {
        "LABEL_SUMBER": fin.LABEL_SUMBER,
        "LABEL_UMUR": fin.LABEL_UMUR,
        "LABEL_TIPE_AKUN": fin.LABEL_TIPE_AKUN,
        "LABEL_ARAH": fin.LABEL_ARAH,
        "TIPE_AKUN": ACCOUNT_TYPES,
        "METODE": PAYMENT_METHODS,
    }


def _saring_tagihan(tagihan: list[dict], q: str) -> list[dict]:
    """Filter daftar utang/piutang berdasarkan nomor faktur atau nama pihak."""
    kata = (q or "").strip().lower()
    if not kata:
        return tagihan
    return [
        b
        for b in tagihan
        if kata in (b["faktur"].number or "").lower() or kata in (b["partner"].nama or "").lower()
    ]


# ---------------------------------------------------------------- ringkasan
@router.get("/finance", response_class=HTMLResponse, include_in_schema=False)
def finance_page(request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    return render(
        request,
        "finance/dashboard.html",
        user,
        "finance",
        ringkas=fin.ringkasan(db, user.organisation_id),
        **_konteks_finance(),
    )


@router.get("/finance/payables", response_class=HTMLResponse, include_in_schema=False)
def payables_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    tagihan = _saring_tagihan(fin.daftar_utang(db, user.organisation_id), q)
    h = halaman(request, tagihan)
    return render(
        request,
        "finance/tagihan.html",
        user,
        "payables",
        judul="Utang Usaha (AP)",
        arah="keluar",
        tagihan=h.items,
        h=h,
        total_faktur=len(tagihan),
        q=q,
        umur=fin.aging(tagihan),
        total=sum((b["sisa"] for b in tagihan), fin.NOL),
        **_konteks_finance(),
    )


@router.get("/finance/receivables", response_class=HTMLResponse, include_in_schema=False)
def receivables_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    tagihan = _saring_tagihan(fin.daftar_piutang(db, user.organisation_id), q)
    h = halaman(request, tagihan)
    return render(
        request,
        "finance/tagihan.html",
        user,
        "receivables",
        judul="Piutang Usaha (AR)",
        arah="masuk",
        tagihan=h.items,
        h=h,
        total_faktur=len(tagihan),
        q=q,
        umur=fin.aging(tagihan),
        total=sum((b["sisa"] for b in tagihan), fin.NOL),
        **_konteks_finance(),
    )


# --------------------------------------------------------------- pembayaran
@router.get("/finance/payments", response_class=HTMLResponse, include_in_schema=False)
def payments_page(request: Request, arah: str = "", q: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    h = halaman(request, fin.list_pembayaran(db, user.organisation_id, arah=arah, q=q, batas=100000))
    return render(
        request,
        "finance/payments.html",
        user,
        "payments",
        payments=h.items,
        h=h,
        arah=arah,
        q=q,
        **_konteks_finance(),
    )


@router.get("/finance/payments/new", response_class=HTMLResponse, include_in_schema=False)
def payment_new(request: Request, arah: str = "keluar", faktur: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    arah = "masuk" if arah == "masuk" else "keluar"
    pilihan = fin.faktur_belum_lunas(db, user.organisation_id, arah)
    terpilih = next((b for b in pilihan if str(b["faktur"].id) == faktur), None)
    return render(
        request,
        "finance/payment_form.html",
        user,
        "payments",
        arah=arah,
        pilihan=pilihan,
        terpilih=terpilih,
        akun=fin.akun_kas(db, user.organisation_id),
        hari_ini=date.today(),
        **_konteks_finance(),
    )


@router.post("/finance/payments", include_in_schema=False)
def payment_create(
    request: Request,
    arah: str = Form("keluar"),
    faktur_id: str = Form(""),
    akun_id: str = Form(""),
    jumlah: str = Form(""),
    tanggal: str = Form(""),
    metode: str = Form("transfer"),
    referensi: str = Form(""),
    catatan: str = Form(""),
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    arah = "masuk" if arah == "masuk" else "keluar"
    try:
        if not faktur_id:
            raise AppError("Faktur belum dipilih.")
        faktur = fin.faktur_untuk_pembayaran(db, user.organisation_id, uuid.UUID(faktur_id), arah)
        sisa = fin.sisa_faktur(db, faktur)
        # jumlah dikosongkan = lunasi sisa tagihan
        nilai = jumlah.strip() or str(sisa)
        pembayaran = fin.catat_pembayaran(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            arah=arah,
            faktur_id=faktur.id,
            akun_id=uuid.UUID(akun_id) if akun_id else fin.akun_kas_default(db, user.organisation_id).id,
            jumlah=nilai,
            tanggal=to_date(tanggal, "Tanggal pembayaran", default=date.today()),
            metode=metode,
            referensi=referensi,
            catatan=catatan,
        )
    except (AppError, ValueError) as exc:
        return flash_err(
            f"/finance/payments/new?arah={arah}" + (f"&faktur={faktur_id}" if faktur_id else ""),
            str(exc),
        )
    return flash_ok(f"/finance/payments/{pembayaran.id}", f"{fin.LABEL_ARAH[arah]} {pembayaran.number} tersimpan.")


@router.get("/finance/payments/{payment_id}", response_class=HTMLResponse, include_in_schema=False)
def payment_detail(payment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        pembayaran = fin.get_pembayaran(db, user.organisation_id, payment_id)
    except AppError as exc:
        return flash_err("/finance/payments", str(exc))
    return render(
        request,
        "finance/payment_detail.html",
        user,
        "payments",
        p=pembayaran,
        **_konteks_finance(),
    )


@router.post("/finance/payments/{payment_id}/hapus", include_in_schema=False)
def payment_delete(payment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        fin.hapus_pembayaran(db, organisation_id=user.organisation_id, payment_id=payment_id)
    except AppError as exc:
        return flash_err("/finance/payments", str(exc))
    return flash_ok("/finance/payments", "Pembayaran dibatalkan; jurnalnya ditandai void.")


# -------------------------------------------------------------------- jurnal
@router.get("/finance/journal", response_class=HTMLResponse, include_in_schema=False)
def journal_page(
    request: Request,
    q: str = "",
    sumber: str = "",
    dari: str = "",
    sampai: str = "",
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db)
    if err:
        return err
    entri = fin.list_jurnal(
        db,
        user.organisation_id,
        q=q,
        sumber=sumber,
        dari=_tanggal_opsional(dari, "Dari"),
        sampai=_tanggal_opsional(sampai, "Sampai"),
        batas=100000,
    )
    h = halaman(request, entri)
    return render(
        request, "finance/journal.html", user, "journal",
        entri=h.items, h=h, q=q, sumber=sumber, dari=dari, sampai=sampai,
        **_konteks_finance(),
    )


@router.get("/finance/journal/{entry_id}", response_class=HTMLResponse, include_in_schema=False)
def journal_detail(entry_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    try:
        entri = fin.get_jurnal(db, user.organisation_id, entry_id)
    except AppError as exc:
        return flash_err("/finance/journal", str(exc))
    return render(
        request, "finance/journal_detail.html", user, "journal", entri=entri, **_konteks_finance()
    )


# -------------------------------------------------------------- bagan akun
@router.get("/finance/accounts", response_class=HTMLResponse, include_in_schema=False)
def accounts_page(request: Request, q: str = "", tipe: str = "", db: Session = Depends(get_db)):
    user, err = _guard(request, db)
    if err:
        return err
    fin.pastikan_coa(db, user.organisation_id)
    db.commit()
    h = halaman(request, fin.list_accounts(db, user.organisation_id, q, tipe))
    return render(
        request, "finance/accounts.html", user, "accounts",
        akun=h.items, h=h,
        saldo={b["akun"].id: b for b in fin.saldo_akun(db, user.organisation_id)},
        q=q, tipe=tipe,
        **_konteks_finance(),
    )


@router.post("/finance/accounts", include_in_schema=False)
def account_create(
    request: Request,
    kode: str = Form(""),
    nama: str = Form(""),
    tipe: str = Form("asset"),
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        akun = fin.buat_akun(db, organisation_id=user.organisation_id, kode=kode, nama=nama, tipe=tipe)
    except AppError as exc:
        return flash_err("/finance/accounts", str(exc))
    return flash_ok("/finance/accounts", f"Akun {akun.kode} — {akun.nama} ditambahkan.")


@router.post("/finance/accounts/{account_id}", include_in_schema=False)
def account_update(
    account_id: uuid.UUID,
    request: Request,
    nama: str = Form(""),
    aktif: str = Form(""),
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db, butuh_tulis=True)
    if err:
        return err
    try:
        fin.ubah_akun(
            db,
            organisation_id=user.organisation_id,
            akun_id=account_id,
            nama=nama,
            aktif=bool(aktif),
        )
    except AppError as exc:
        return flash_err("/finance/accounts", str(exc))
    return flash_ok("/finance/accounts", "Akun diperbarui.")


# ------------------------------------------------------------------ laporan
@router.get("/finance/trial-balance", response_class=HTMLResponse, include_in_schema=False)
def trial_balance(
    request: Request,
    dari: str = "",
    sampai: str = "",
    db: Session = Depends(get_db),
):
    user, err = _guard(request, db)
    if err:
        return err
    baris = fin.saldo_akun(
        db,
        user.organisation_id,
        dari=_tanggal_opsional(dari, "Dari"),
        sampai=_tanggal_opsional(sampai, "Sampai"),
    )
    h = halaman(request, baris)
    return render(
        request, "finance/trial_balance.html", user, "trial",
        baris=h.items, h=h,
        total_debit=sum((b["debit"] for b in baris), fin.NOL),
        total_kredit=sum((b["credit"] for b in baris), fin.NOL),
        dari=dari, sampai=sampai,
        **_konteks_finance(),
    )
