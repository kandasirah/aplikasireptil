"""Titik masuk aplikasi REPTIL (FastAPI)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from reptil import __version__
from reptil.core.config import get_settings
from reptil.core.db import check_connection
from reptil.core.errors import register_exception_handlers
from reptil.core.logging import configure_logging
from reptil.modules.database.web import router as database_web
from reptil.modules.finance.api import router as finance_api
from reptil.modules.finance.web import router as finance_web
from reptil.modules.identity.api import router as auth_router
from reptil.modules.identity.rbac_api import router as rbac_api
from reptil.modules.identity.web import router as identity_web
from reptil.modules.inventory.api import router as inventory_api
from reptil.modules.inventory.web import router as inventory_web
from reptil.modules.logistics.api import router as logistics_api
from reptil.modules.logistics.web import router as logistics_web
from reptil.modules.masterdata.api import router as masterdata_api
from reptil.modules.masterdata.web import router as masterdata_web
from reptil.modules.pengaturan.api import router as pengaturan_api
from reptil.modules.pengaturan.web import router as pengaturan_web
from reptil.modules.purchasing.api import router as purchasing_api
from reptil.modules.purchasing.web import router as purchasing_web
from reptil.modules.reporting.api import router as reporting_api
from reptil.modules.reporting.web import router as reporting_web
from reptil.modules.sales.api import router as sales_api
from reptil.modules.sales.web import router as sales_web
from reptil.web.pages import router as web_router

settings = get_settings()

# Log terstruktur: JSON di produksi, konsol berwarna saat pengembangan
configure_logging(json_logs=settings.is_production)

app = FastAPI(
    title=f"{settings.app_name} API",
    description="Reliable Enterprise Platform for Technology, Integration & Logistics",
    version=__version__,
)

# Error domain → JSON (API) atau halaman HTML ringkas (browser), plus log 500
register_exception_handlers(app)

static_dir = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# API JSON (Swagger)
app.include_router(auth_router)
app.include_router(rbac_api)
app.include_router(masterdata_api)
app.include_router(inventory_api)
app.include_router(purchasing_api)
app.include_router(sales_api)
app.include_router(finance_api)
app.include_router(logistics_api)
app.include_router(reporting_api)
app.include_router(pengaturan_api)

# Halaman web
app.include_router(web_router)
app.include_router(identity_web)
app.include_router(masterdata_web)
app.include_router(inventory_web)
app.include_router(purchasing_web)
app.include_router(sales_web)
app.include_router(finance_web)
app.include_router(reporting_web)
app.include_router(logistics_web)
app.include_router(pengaturan_web)
app.include_router(database_web)


@app.get("/health", tags=["sistem"])
def health() -> dict:
    try:
        info = check_connection()
        return {"status": "ok", "database": "ok", "server": info["server_version"]}
    except Exception as exc:  # health check harus selalu membalas
        return {"status": "degraded", "database": "error", "detail": str(exc)}
