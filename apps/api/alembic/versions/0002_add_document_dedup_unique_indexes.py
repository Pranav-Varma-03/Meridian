"""add document dedup unique indexes

Revision ID: 0002_add_document_dedup_unique_indexes
Revises: 0001_milestone1_core
Create Date: 2026-04-16 09:35:00
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_document_dedup_unique_indexes"
down_revision = "0001_milestone1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
