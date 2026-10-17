"""Domain event bus in-process REPTIL.

Komunikasi antar-modul sebisa mungkin lewat event, bukan panggilan langsung
(lihat docs/DESAIN.md §3 & §6). Bus ini sinkron dan in-process; pemetaan ke
Celery task dilakukan di layer worker, sehingga implementasi bisa diganti
tukar tanpa mengubah pemanggil.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainEvent:
    """Induk semua event domain. Subclass menambah field spesifik."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def name(self) -> str:
        return type(self).__name__


Handler = Callable[[DomainEvent], None]


class EventBus:
    """Registry handler per tipe event + dispatch sinkron.

    Handler yang gagal tidak menggagalkan handler lain (di-log, bukan raise),
    karena side-effect non-kritis (mis. email) tidak boleh membatalkan transaksi.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """Kirim event ke semua handler untuk tipenya (termasuk handler superclass)."""
        for event_type, handlers in self._handlers.items():
            if isinstance(event, event_type):
                for handler in list(handlers):
                    try:
                        handler(event)
                    except Exception:
                        logger.exception(
                            "Handler event gagal", extra={"event": event.name}
                        )

    def clear(self) -> None:
        self._handlers.clear()


# Bus global untuk aplikasi (dipasang handler oleh tiap modul saat import).
event_bus = EventBus()


# ---------------------------------------------------------------------------
# Event lintas-modul (shared contract). Event spesifik modul didefinisikan di
# `modules/<nama>/events.py` dan boleh mewarisi salah satu di bawah.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoodsReceived(DomainEvent):
    """Barang diterima (GR) — dikonsumsi inventory untuk membuat mutasi stok."""

    goods_receipt_id: str = ""
    organisation_id: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class StockReserved(DomainEvent):
    """Stok di-reserve oleh Sales Order."""

    sales_order_id: str = ""
    organisation_id: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentStatusChanged(DomainEvent):
    """Status pengiriman berubah — dikonsumsi reporting & integration."""

    shipment_id: str = ""
    status: str = ""
    note: str | None = None
