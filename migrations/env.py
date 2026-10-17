"""Alembic env — koneksi diambil dari konfigurasi aplikasi (src/reptil/core/config.py)."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Pastikan paket `reptil` bisa diimpor saat alembic dijalankan dari root repo
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reptil.core.config import get_settings  # noqa: E402

config = context.config

# Timpa sqlalchemy.url di alembic.ini dengan DATABASE_URL dari .env
config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import semua model agar autogenerate mendeteksinya.
from reptil.modules.database import models as database_models  # noqa: F401, E402
from reptil.modules.identity import models as identity_models  # noqa: F401, E402
from reptil.modules.inventory import models as inventory_models  # noqa: F401, E402
from reptil.modules.finance import models as finance_models  # noqa: F401, E402
from reptil.modules.logistics import models as logistics_models  # noqa: F401, E402
from reptil.modules.masterdata import models as masterdata_models  # noqa: F401, E402
from reptil.modules.pengaturan import models as pengaturan_models  # noqa: F401, E402
from reptil.modules.purchasing import models as purchasing_models  # noqa: F401, E402
from reptil.modules.sales import models as sales_models  # noqa: F401, E402

from reptil.core.metadata import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
