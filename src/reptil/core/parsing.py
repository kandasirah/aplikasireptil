"""Parser nilai dari form/API: aman (selalu raise BusinessRuleError, bukan ValueError)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from reptil.core.errors import BusinessRuleError


def to_decimal(value: str | int | float | Decimal | None, field: str, default: Decimal | None = None) -> Decimal:
    if value is None or value == "":
        if default is not None:
            return default
        raise BusinessRuleError(f"{field} wajib diisi.")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise BusinessRuleError(f"{field} bukan angka yang valid: {value}") from exc


def to_date(value: str | date | None, field: str, default: date | None = None) -> date:
    if value is None or value == "":
        if default is not None:
            return default
        raise BusinessRuleError(f"{field} wajib diisi.")
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BusinessRuleError(f"{field} harus format YYYY-MM-DD.") from exc
