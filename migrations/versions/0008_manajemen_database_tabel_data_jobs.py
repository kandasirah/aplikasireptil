"""manajemen database: tabel data_jobs

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'data_jobs',
        sa.Column('organisation_id', sa.UUID(), nullable=False),
        sa.Column('jenis', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('tahap', sa.String(length=150), nullable=True),
        sa.Column('persen', sa.Integer(), nullable=False),
        sa.Column(
            'parameter',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('hasil', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pesan', sa.Text(), nullable=True),
        sa.Column('mulai_pada', sa.DateTime(timezone=True), nullable=True),
        sa.Column('selesai_pada', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jenis IN ('demo','reset')", name=op.f('ck_data_jobs_jenis_valid')
        ),
        sa.CheckConstraint(
            "status IN ('menunggu','berjalan','selesai','gagal')",
            name=op.f('ck_data_jobs_status_valid'),
        ),
        sa.CheckConstraint(
            "persen >= 0 AND persen <= 100", name=op.f('ck_data_jobs_persen_valid')
        ),
        sa.ForeignKeyConstraint(
            ['created_by'],
            ['users.id'],
            name=op.f('fk_data_jobs_created_by_users'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['organisation_id'],
            ['organisations.id'],
            name=op.f('fk_data_jobs_organisation_id_organisations'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_jobs')),
    )
    op.create_index(
        op.f('ix_data_jobs_organisation_id'),
        'data_jobs',
        ['organisation_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_data_jobs_organisation_id'), table_name='data_jobs')
    op.drop_table('data_jobs')
