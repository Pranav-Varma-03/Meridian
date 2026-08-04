"""add separately versioned derived chunk context

Revision ID: 0008_derived_chunk_context
Revises: 0007_parent_child_retrieval_state
Create Date: 2026-08-04 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_derived_chunk_context"
down_revision = "0007_parent_child_retrieval_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks", sa.Column("derived_context_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column("derived_context_version", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "derived_context_version")
    op.drop_column("document_chunks", "derived_context_text")
