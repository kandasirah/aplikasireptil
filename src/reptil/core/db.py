"""Engine, session, dan unit-of-work dasar REPTIL (SQLAlchemy 2.x)."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from reptil.core.config import get_settings


def build_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,       # deteksi koneksi putus sebelum dipakai
        pool_size=10,
        max_overflow=20,
        future=True,
    )


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: satu session per request, rollback bila gagal."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Untuk skrip & worker: commit otomatis, rollback bila error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_connection() -> dict:
    """Tes koneksi + info server. Mengembalikan dict; tidak raise."""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
        settings = get_settings()
        return {
            "status": "ok",
            "server_version": version,
            "database": settings.database_name,
            "user": settings.database_user,
            "host": f"{settings.database_host}:{settings.database_port}",
        }
