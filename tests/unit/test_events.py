"""Uji domain event bus in-process."""

from __future__ import annotations

from dataclasses import dataclass

from reptil.core.events import DomainEvent, EventBus, GoodsReceived


@dataclass(frozen=True)
class _Halo(DomainEvent):
    nama: str = ""


def test_publish_sampai_ke_subscriber() -> None:
    bus = EventBus()
    diterima: list[str] = []
    bus.subscribe(_Halo, lambda e: diterima.append(e.nama))  # type: ignore[arg-type]

    bus.publish(_Halo(nama="reptil"))

    assert diterima == ["reptil"]


def test_handler_lain_tetap_jalan_saat_satu_gagal() -> None:
    bus = EventBus()
    urutan: list[str] = []

    def gagal(_: DomainEvent) -> None:
        raise RuntimeError("handler non-kritis gagal")

    bus.subscribe(_Halo, gagal)
    bus.subscribe(_Halo, lambda _: urutan.append("kedua"))

    bus.publish(_Halo())  # tidak boleh melempar

    assert urutan == ["kedua"]


def test_event_mendapat_handler_superclass() -> None:
    bus = EventBus()
    jumlah: list[int] = []
    bus.subscribe(DomainEvent, lambda _: jumlah.append(1))

    bus.publish(GoodsReceived(goods_receipt_id="gr-1"))

    assert jumlah == [1]


def test_unsubscribe_menghentikan_pengiriman() -> None:
    bus = EventBus()
    diterima: list[str] = []
    handler = lambda e: diterima.append(e.nama)  # noqa: E731
    bus.subscribe(_Halo, handler)  # type: ignore[arg-type]

    bus.publish(_Halo(nama="a"))
    bus.unsubscribe(_Halo, handler)
    bus.publish(_Halo(nama="b"))

    assert diterima == ["a"]
