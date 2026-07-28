"""add durable conversation retrieval scopes

Revision ID: 0006_conversation_retrieval_scopes
Revises: 0005_conversation_memory
Create Date: 2026-07-28 12:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_conversation_retrieval_scopes"
down_revision = "0005_conversation_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    scope_mode = postgresql.ENUM("all", "collections", name="retrieval_scope_mode")
    scope_mode.create(op.get_bind(), checkfirst=True)

    # The enum is created explicitly above so it can be shared by both tables.
    # Suppress SQLAlchemy's table-level enum DDL; otherwise create_table() tries
    # to issue a second CREATE TYPE in the same migration transaction.
    scope_mode_column = postgresql.ENUM(
        "all", "collections", name="retrieval_scope_mode", create_type=False
    )
    op.create_table(
        "conversation_retrieval_scopes",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mode", scope_mode_column, nullable=False),
        sa.Column(
            "collection_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "conversation_scope_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effective_from_sequence", sa.Integer(), nullable=False),
        sa.Column("mode", scope_mode_column, nullable=False),
        sa.Column(
            "collection_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("scope_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "effective_from_sequence",
            name="uq_conversation_scope_event_sequence",
        ),
    )
    op.create_index(
        "ix_conversation_scope_events_conversation_id",
        "conversation_scope_events",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_scope_events_conversation_id",
        table_name="conversation_scope_events",
    )
    op.drop_table("conversation_scope_events")
    op.drop_table("conversation_retrieval_scopes")
    postgresql.ENUM(name="retrieval_scope_mode").drop(op.get_bind(), checkfirst=True)
