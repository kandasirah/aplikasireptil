"""Exception domain REPTIL + pemetaan otomatis ke HTTP.

Service melempar exception domain (bukan HTTPException) agar layer bisnis
tidak tahu-menahu soal HTTP. Handler di bawah ini menerjemahkannya ke respons
JSON yang konsisten:

    {"error": {"code": "not_found", "message": "...", "detail": {...}}}

Untuk permintaan halaman (browser, `Accept: text/html`) balasannya berupa
halaman HTML sederhana, bukan JSON — supaya pengguna web tidak melihat tumpukan
JSON mentah saat terjadi kesalahan.
"""

from __future__ import annotations

import html
import traceback
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from reptil.core.logging import get_logger, get_correlation_id


class AppError(Exception):
    """Induk semua error domain REPTIL."""

    code: str = "app_error"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Terjadi kesalahan pada aplikasi."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.detail = detail or {}

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class NotFoundError(AppError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND
    message = "Data tidak ditemukan."


class ConflictError(AppError):
    code = "conflict"
    http_status = status.HTTP_409_CONFLICT
    message = "Data bertentangan dengan data yang sudah ada."


class BusinessRuleError(AppError):
    """Aturan bisnis dilanggar (mis. stok tidak cukup, qty negatif)."""

    code = "business_rule"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Aturan bisnis tidak terpenuhi."


class AuthenticationError(AppError):
    code = "unauthenticated"
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "Autentikasi diperlukan."


class PermissionDeniedError(AppError):
    code = "forbidden"
    http_status = status.HTTP_403_FORBIDDEN
    message = "Anda tidak punya izin untuk aksi ini."


def _error_response(status_code: int, payload: dict[str, Any]) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(status_code=status_code, content={"error": payload}, headers=headers)


def _ingin_json(request: Request) -> bool:
    """True bila pemanggil lebih mengharapkan JSON daripada halaman HTML.

    Hanya klien yang secara eksplisit menerima ``text/html`` (browser) yang
    mendapat halaman HTML; sisanya (``*/*``, ``application/json``, tanpa header)
    mendapat amplop JSON.
    """
    if request.url.path.startswith(("/api/", "/docs", "/redoc", "/openapi.json")):
        return True
    accept = (request.headers.get("accept") or "*/*").lower()
    return "text/html" not in accept


def _halaman_error(status_code: int, pesan: str) -> HTMLResponse:
    """Halaman error ringkas yang berdiri sendiri (tanpa template aplikasi)."""
    return HTMLResponse(
        status_code=status_code,
        content=f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kesalahan {status_code}</title>
<style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#f4f7f5;
         font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif; color:#1f2a24; }}
  .kotak {{ background:#fff; border:1px solid #dde7e0; border-radius:14px; padding:34px 38px;
            max-width:520px; text-align:center; box-shadow:0 8px 26px rgba(15,81,50,.07); }}
  .kode {{ font-size:44px; font-weight:800; color:#0f5132; line-height:1; }}
  h1 {{ font-size:17px; margin:14px 0 6px; }}
  p {{ margin:0 0 20px; font-size:13.5px; line-height:1.55; color:#5c6b62; }}
  a {{ display:inline-block; background:#0f5132; color:#fff; text-decoration:none;
       padding:9px 18px; border-radius:8px; font-size:13.5px; font-weight:600; }}
</style></head>
<body><div class="kotak">
  <div class="kode">{status_code}</div>
  <h1>Tidak dapat memproses permintaan</h1>
  <p>{html.escape(pesan)}</p>
  <a href="/dashboard">Kembali ke Dashboard</a>
</div></body></html>""",
    )


def _balasan(request: Request, status_code: int, payload: dict[str, Any]) -> Response:
    if _ingin_json(request):
        return _error_response(status_code, payload)
    return _halaman_error(status_code, payload.get("message") or "Terjadi kesalahan.")


def _ringkas_validasi(errors: list[dict[str, Any]]) -> str:
    bagian: list[str] = []
    for galat in errors:
        lokasi = " → ".join(
            str(x) for x in galat.get("loc", ()) if x not in ("body", "query", "path", "header")
        )
        pesan = str(galat.get("msg") or "tidak valid")
        bagian.append(f"{lokasi}: {pesan}" if lokasi else pesan)
    return "; ".join(bagian) or "Data kiriman tidak lengkap."


def register_exception_handlers(app: FastAPI) -> None:
    """Pasang handler error terpusat pada instance FastAPI."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> Response:
        return _balasan(request, exc.http_status, exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> Response:
        errors = jsonable_encoder(exc.errors())
        return _balasan(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "validation_error",
                "message": _ringkas_validasi(errors),
                "detail": {"errors": errors},
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> Response:
        return _balasan(
            request,
            exc.status_code,
            {"code": "http_error", "message": str(exc.detail)},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> Response:
        """Jaring terakhir: catat jejak lengkap, jangan bocorkan ke pengguna."""
        logger = get_logger("reptil.error")
        logger.error(
            "unhandled_error",
            path=request.url.path,
            method=request.method,
            error_type=exc.__class__.__name__,
            error=str(exc),
            traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )
        payload: dict[str, Any] = {
            "code": "internal_error",
            "message": "Terjadi kesalahan internal. Silakan coba lagi; "
            "bila berulang hubungi administrator.",
        }
        cid = get_correlation_id()
        if cid:
            payload["detail"] = {"correlation_id": cid}
        return _balasan(request, status.HTTP_500_INTERNAL_SERVER_ERROR, payload)
