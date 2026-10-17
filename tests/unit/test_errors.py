"""Uji pemetaan exception domain → respons HTTP terpusat."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reptil.core.errors import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    register_exception_handlers,
)


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/nf")
    def nf() -> None:
        raise NotFoundError("Partner tidak ditemukan.", detail={"kode": "C-999"})

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("Kode sudah dipakai.")

    @app.get("/business")
    def business() -> None:
        raise BusinessRuleError("Stok tidak cukup.")

    return TestClient(app)


def test_not_found_maps_to_404_with_payload() -> None:
    resp = _client().get("/nf")
    assert resp.status_code == 404
    body = resp.json()["error"]
    assert body["code"] == "not_found"
    assert body["message"] == "Partner tidak ditemukan."
    assert body["detail"] == {"kode": "C-999"}


def test_conflict_maps_to_409() -> None:
    resp = _client().get("/conflict")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_business_rule_maps_to_422() -> None:
    resp = _client().get("/business")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "business_rule"
