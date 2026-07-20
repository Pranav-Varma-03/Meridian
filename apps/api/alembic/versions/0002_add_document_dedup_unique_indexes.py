"""add document dedup unique indexes

Revision ID: 0002_add_document_dedup_unique_indexes
Revises: 0001_milestone1_core
Create Date: 2026-04-16 09:35:00
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_document_dedup_unique_indexes"
down_revision = "0001_milestone1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic creates this table with VARCHAR(32) by default, while this
    # project's descriptive revision IDs are longer. Widen it before Alembic
    # writes this revision identifier at the end of the upgrade transaction.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_index(
        "uq_documents_user_file_hash",
        "documents",
        ["user_id", "file_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_documents_user_file_hash",
        table_name="documents",
    )
