"""add durable retry scheduling to ingestion jobs

Revision ID: 0004_add_ingestion_job_retry_schedule
Revises: 0003_document_ingestion_generations
Create Date: 2026-07-21 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_add_ingestion_job_retry_schedule"
down_revision = "0003_document_ingestion_generations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ingestion_jobs_next_attempt_at",
        "ingestion_jobs",
        ["next_attempt_at"],
        unique=False,
    )
    op.add_column(
        "purge_jobs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_purge_jobs_started_at",
        "purge_jobs",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_purge_jobs_started_at", table_name="purge_jobs")
    op.drop_column("purge_jobs", "started_at")
    op.drop_index("ix_ingestion_jobs_next_attempt_at", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "next_attempt_at")
