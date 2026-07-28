"""add conversation memory and deterministic message ordering

Revision ID: 0005_conversation_memory
Revises: 0004_add_ingestion_job_retry_schedule
Create Date: 2026-07-24 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_conversation_memory"
down_revision = "0004_add_ingestion_job_retry_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sequence_number", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH ordered_messages AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY conversation_id ORDER BY created_at, id
            ) AS sequence_number
            FROM messages
        )
        UPDATE messages
        SET sequence_number = ordered_messages.sequence_number
        FROM ordered_messages
        WHERE messages.id = ordered_messages.id
        """
    )
    op.alter_column("messages", "sequence_number", nullable=False)
    op.create_unique_constraint(
        "uq_messages_conversation_sequence",
        "messages",
        ["conversation_id", "sequence_number"],
    )
    op.create_index(
        "ix_messages_conversation_sequence",
        "messages",
        ["conversation_id", "sequence_number"],
        unique=False,
    )
    op.create_table(
        "conversation_memories",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("summary_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "summarized_through_sequence",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_memories")
    op.drop_index("ix_messages_conversation_sequence", table_name="messages")
    op.drop_constraint("uq_messages_conversation_sequence", "messages", type_="unique")
    op.drop_column("messages", "sequence_number")
