"""Uji kalkulasi beban rute logistik (tanpa DB)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from reptil.modules.logistics.service import route_load


def _stop(jarak: str, berat: str | None = None, volume: str | None = None):
    shipment = None
    if berat is not None and volume is not None:
        shipment = SimpleNamespace(
            total_berat_kg=Decimal(berat), total_volume_m3=Decimal(volume)
        )
    return SimpleNamespace(jarak_km=Decimal(jarak), shipment=shipment)


def test_route_load_menjumlah_jarak_dan_kiriman() -> None:
    route = SimpleNamespace(
        stops=[
            _stop("12.5", berat="27", volume="0.37"),
            _stop("5"),
            _stop("3.25", berat="10.5", volume="0.1"),
        ]
    )

    load = route_load(route)  # type: ignore[arg-type]

    assert load["total_jarak_km"] == Decimal("20.75")
    assert load["total_berat_kg"] == Decimal("37.5")
    assert load["total_volume_m3"] == Decimal("0.47")


def test_route_load_tanpa_titik_nol() -> None:
    load = route_load(SimpleNamespace(stops=[]))  # type: ignore[arg-type]

    assert load["total_jarak_km"] == Decimal("0")
    assert load["total_berat_kg"] == Decimal("0")
