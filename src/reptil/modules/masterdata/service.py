"""Service master data REPTIL — CRUD Partner, Item, Warehouse."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reptil.core.errors import BusinessRuleError, NotFoundError
from reptil.core.parsing import to_decimal
from reptil.modules.masterdata.models import ITEM_TYPES, PARTNER_TYPES, Item, Partner, Warehouse


# --------------------------------------------------------------------- partner
def list_partners(db: Session, organisation_id: uuid.UUID, q: str = "", tipe: str = "") -> list[Partner]:
    stmt = select(Partner).where(Partner.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Partner.nama.ilike(like) | Partner.kode.ilike(like))
    if tipe in PARTNER_TYPES:
        stmt = stmt.where(Partner.tipe.in_([tipe, "both"]))
    return list(db.execute(stmt.order_by(Partner.nama)).scalars().all())


def get_partner(db: Session, organisation_id: uuid.UUID, partner_id: uuid.UUID) -> Partner:
    obj = db.execute(
        select(Partner).where(Partner.id == partner_id, Partner.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Partner tidak ditemukan.")
    return obj


def save_partner(db: Session, organisation_id: uuid.UUID, data: dict, partner_id: uuid.UUID | None = None) -> Partner:
    kode = (data.get("kode") or "").strip()
    nama = (data.get("nama") or "").strip()
    tipe = data.get("tipe") or "customer"
    if not kode:
        raise BusinessRuleError("Kode partner wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama partner wajib diisi.")
    if tipe not in PARTNER_TYPES:
        raise BusinessRuleError("Tipe partner harus customer, supplier, atau both.")

    obj = get_partner(db, organisation_id, partner_id) if partner_id else Partner(organisation_id=organisation_id)
    obj.kode, obj.nama, obj.tipe = kode, nama, tipe
    obj.npwp = (data.get("npwp") or "").strip() or None
    obj.email = (data.get("email") or "").strip() or None
    obj.telepon = (data.get("telepon") or "").strip() or None
    obj.alamat = (data.get("alamat") or "").strip() or None
    obj.is_active = bool(data.get("is_active", True))

    db.add(obj)
    _commit(db, f"Kode partner '{kode}' sudah dipakai.")
    return obj


# ------------------------------------------------------------------------ item
def list_items(db: Session, organisation_id: uuid.UUID, q: str = "", aktif: bool | None = None) -> list[Item]:
    stmt = select(Item).where(Item.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Item.nama.ilike(like) | Item.sku.ilike(like))
    if aktif is not None:
        stmt = stmt.where(Item.is_active.is_(aktif))
    return list(db.execute(stmt.order_by(Item.nama)).scalars().all())


def get_item(db: Session, organisation_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    obj = db.execute(
        select(Item).where(Item.id == item_id, Item.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Item tidak ditemukan.")
    return obj


def save_item(db: Session, organisation_id: uuid.UUID, data: dict, item_id: uuid.UUID | None = None) -> Item:
    sku = (data.get("sku") or "").strip()
    nama = (data.get("nama") or "").strip()
    tipe = data.get("tipe") or "produk"
    if not sku:
        raise BusinessRuleError("SKU wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama item wajib diisi.")
    if tipe not in ITEM_TYPES:
        raise BusinessRuleError("Tipe item harus produk atau jasa.")

    obj = get_item(db, organisation_id, item_id) if item_id else Item(organisation_id=organisation_id)
    obj.sku, obj.nama, obj.tipe = sku, nama, tipe
    obj.deskripsi = (data.get("deskripsi") or "").strip() or None
    obj.satuan = (data.get("satuan") or "pcs").strip()
    obj.berat_kg = to_decimal(data.get("berat_kg"), "Berat (kg)", default=Decimal("0"))
    obj.volume_m3 = to_decimal(data.get("volume_m3"), "Volume (m³)", default=Decimal("0"))
    obj.harga_beli = to_decimal(data.get("harga_beli"), "Harga beli", default=Decimal("0"))
    obj.harga_jual = to_decimal(data.get("harga_jual"), "Harga jual", default=Decimal("0"))
    obj.stok_minimum = to_decimal(data.get("stok_minimum"), "Stok minimum", default=Decimal("0"))
    if obj.berat_kg < 0 or obj.volume_m3 < 0:
        raise BusinessRuleError("Berat dan volume tidak boleh negatif.")
    obj.is_active = bool(data.get("is_active", True))

    db.add(obj)
    _commit(db, f"SKU '{sku}' sudah dipakai.")
    return obj


# ------------------------------------------------------------------- warehouse
def list_warehouses(db: Session, organisation_id: uuid.UUID, q: str = "") -> list[Warehouse]:
    stmt = select(Warehouse).where(Warehouse.organisation_id == organisation_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Warehouse.nama.ilike(like) | Warehouse.kode.ilike(like))
    return list(db.execute(stmt.order_by(Warehouse.nama)).scalars().all())


def get_warehouse(db: Session, organisation_id: uuid.UUID, warehouse_id: uuid.UUID) -> Warehouse:
    obj = db.execute(
        select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.organisation_id == organisation_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Gudang tidak ditemukan.")
    return obj


def save_warehouse(
    db: Session, organisation_id: uuid.UUID, data: dict, warehouse_id: uuid.UUID | None = None
) -> Warehouse:
    kode = (data.get("kode") or "").strip()
    nama = (data.get("nama") or "").strip()
    if not kode:
        raise BusinessRuleError("Kode gudang wajib diisi.")
    if not nama:
        raise BusinessRuleError("Nama gudang wajib diisi.")

    obj = (
        get_warehouse(db, organisation_id, warehouse_id)
        if warehouse_id
        else Warehouse(organisation_id=organisation_id)
    )
    obj.kode, obj.nama = kode, nama
    obj.alamat = (data.get("alamat") or "").strip() or None
    obj.is_default = bool(data.get("is_default", False))
    obj.is_active = bool(data.get("is_active", True))

    db.add(obj)
    _commit(db, f"Kode gudang '{kode}' sudah dipakai.")
    return obj


# -------------------------------------------------------------------- internal
def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessRuleError(conflict_message) from exc
