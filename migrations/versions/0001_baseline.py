"""baseline — rekam titik awal skema REPTIL (belum ada tabel; model menyusul).

Revision ID: 0001
Revisi:
- Create Date: 2026-10-17
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Titik awal kosong — tabel dibuat oleh migrasi berikutnya (autogenerate).
    pass


def downgrade() -> None:
    pass
