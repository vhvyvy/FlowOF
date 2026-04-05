"""tenant onboarding columns, tenant_sources, sync_log

Revision ID: 20260405_01
Revises:
Create Date: 2026-04-05

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260405_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("onboarding_step", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("tenants", sa.Column("source_type", sa.String(length=64), nullable=True))
    op.add_column("tenants", sa.Column("last_sync_at", sa.DateTime(), nullable=True))
    op.add_column(
        "tenants",
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
    )
    op.add_column("tenants", sa.Column("agency_name", sa.String(length=255), nullable=True))

    op.create_table(
        "tenant_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("credentials", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mapping_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tenant_sources_tenant_id"),
        "tenant_sources",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "rows_imported",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "rows_skipped",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sync_log_tenant_id"),
        "sync_log",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_log_tenant_id"), table_name="sync_log")
    op.drop_table("sync_log")
    op.drop_index(op.f("ix_tenant_sources_tenant_id"), table_name="tenant_sources")
    op.drop_table("tenant_sources")

    op.drop_column("tenants", "agency_name")
    op.drop_column("tenants", "currency")
    op.drop_column("tenants", "last_sync_at")
    op.drop_column("tenants", "source_type")
    op.drop_column("tenants", "onboarding_completed")
    op.drop_column("tenants", "onboarding_step")
