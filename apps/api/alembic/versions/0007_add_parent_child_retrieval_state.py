"""add parent child retrieval state

Revision ID: 0007_parent_child_retrieval_state
Revises: 0006_conversation_retrieval_scopes
Create Date: 2026-08-04 10:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_parent_child_retrieval_state"
down_revision = "0006_conversation_retrieval_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_parent_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_ingestion_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_index", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "section_path",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "document_id",
            "generation_id",
            "parent_index",
            name="uq_parent_window_generation_order",
        ),
    )
    op.create_index(
        "ix_parent_windows_document_generation_order",
        "document_parent_windows",
        ["document_id", "generation_id", "parent_index"],
    )

    op.add_column(
        "document_chunks",
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_parent_windows.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "previous_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "next_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "document_chunks", sa.Column("embedding_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "section_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "document_chunks", sa.Column("page_start", sa.Integer(), nullable=True)
    )
    op.add_column("document_chunks", sa.Column("page_end", sa.Integer(), nullable=True))
    op.add_column(
        "document_chunks", sa.Column("source_start", sa.Integer(), nullable=True)
    )
    op.add_column(
        "document_chunks", sa.Column("source_end", sa.Integer(), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column("strategy_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("lexical_search", postgresql.TSVECTOR(), nullable=True),
    )

    op.create_index(
        "ix_chunks_generation_parent", "document_chunks", ["generation_id", "parent_id"]
    )
    op.create_index(
        "ix_chunks_document_generation_order",
        "document_chunks",
        ["document_id", "generation_id", "chunk_index"],
    )
    op.create_index(
        "ix_chunks_lexical_search",
        "document_chunks",
        ["lexical_search"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_lexical_search", table_name="document_chunks")
    op.drop_index("ix_chunks_document_generation_order", table_name="document_chunks")
    op.drop_index("ix_chunks_generation_parent", table_name="document_chunks")
    op.drop_column("document_chunks", "lexical_search")
    op.drop_column("document_chunks", "strategy_version")
    op.drop_column("document_chunks", "source_end")
    op.drop_column("document_chunks", "source_start")
    op.drop_column("document_chunks", "page_end")
    op.drop_column("document_chunks", "page_start")
    op.drop_column("document_chunks", "section_path")
    op.drop_column("document_chunks", "embedding_text")
    op.drop_column("document_chunks", "next_chunk_id")
    op.drop_column("document_chunks", "previous_chunk_id")
    op.drop_column("document_chunks", "parent_id")
    op.drop_index(
        "ix_parent_windows_document_generation_order",
        table_name="document_parent_windows",
    )
    op.drop_table("document_parent_windows")
