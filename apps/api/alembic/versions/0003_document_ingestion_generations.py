"""add durable document ingestion generations and purge state

Revision ID: 0003_document_ingestion_generations
Revises: 0002_add_document_dedup_unique_indexes
Create Date: 2026-07-17 18:00:00
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_document_ingestion_generations"
down_revision = "0002_add_document_dedup_unique_indexes"
branch_labels = None
depends_on = None


document_lifecycle_status_enum = postgresql.ENUM(
    "active",
    "deleting",
    "deleted",
    name="document_lifecycle_status",
    create_type=False,
)
document_generation_status_enum = postgresql.ENUM(
    "pending",
    "active",
    "superseded",
    "failed",
    "purged",
    name="document_generation_status",
    create_type=False,
)
purge_job_status_enum = postgresql.ENUM(
    "queued",
    "running",
    "retryable",
    "complete",
    "terminal_failed",
    name="purge_job_status",
    create_type=False,
)


def _create_enum(name: str, values: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {name} AS ENUM ({values});
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def upgrade() -> None:
    _create_enum("document_lifecycle_status", "'active', 'deleting', 'deleted'")
    _create_enum(
        "document_generation_status",
        "'pending', 'active', 'superseded', 'failed', 'purged'",
    )
    _create_enum(
        "purge_job_status",
        "'queued', 'running', 'retryable', 'complete', 'terminal_failed'",
    )

    op.add_column(
        "documents",
        sa.Column(
            "lifecycle_status",
            document_lifecycle_status_enum,
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("active_generation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "document_ingestion_generations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            document_generation_status_enum,
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_document_generation_number",
        "document_ingestion_generations",
        ["document_id", "generation_number"],
        unique=True,
    )
    op.create_index(
        "ix_document_ingestion_generations_document_id",
        "document_ingestion_generations",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_ingestion_generations_status",
        "document_ingestion_generations",
        ["status"],
        unique=False,
    )

    op.create_table(
        "generation_vector_manifests",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_ingestion_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vector_id", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_generation_vector_id",
        "generation_vector_manifests",
        ["generation_id", "vector_id"],
        unique=True,
    )
    op.create_index(
        "ix_generation_vector_manifests_generation_id",
        "generation_vector_manifests",
        ["generation_id"],
        unique=False,
    )

    op.create_table(
        "purge_jobs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
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
            nullable=True,
        ),
        sa.Column(
            "status", purge_job_status_enum, nullable=False, server_default="queued"
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_purge_job_idempotency_key", "purge_jobs", ["idempotency_key"], unique=True
    )
    op.create_index(
        "ix_purge_jobs_document_id", "purge_jobs", ["document_id"], unique=False
    )
    op.create_index(
        "ix_purge_jobs_generation_id", "purge_jobs", ["generation_id"], unique=False
    )
    op.create_index("ix_purge_jobs_status", "purge_jobs", ["status"], unique=False)
    op.create_index(
        "ix_purge_jobs_next_attempt_at", "purge_jobs", ["next_attempt_at"], unique=False
    )

    op.create_table(
        "outbox_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_outbox_events_topic", "outbox_events", ["topic"], unique=False)
    op.create_index(
        "ix_outbox_events_available_at", "outbox_events", ["available_at"], unique=False
    )
    op.create_index(
        "ix_outbox_events_published_at", "outbox_events", ["published_at"], unique=False
    )

    bind = op.get_bind()
    documents = bind.execute(sa.text("SELECT id, status FROM documents")).mappings()
    for document in documents:
        generation_id = uuid.uuid4()
        status = str(document["status"])
        generation_status = (
            "active"
            if status == "ready"
            else "failed"
            if status == "failed"
            else "pending"
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO document_ingestion_generations
                    (id, document_id, generation_number, status, reason, configuration)
                VALUES (:id, :document_id, 1, :status, 'legacy_backfill', '{}'::jsonb)
                """
            ),
            {
                "id": generation_id,
                "document_id": document["id"],
                "status": generation_status,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE document_chunks SET generation_id = :generation_id WHERE document_id = :document_id"
            ),
            {"generation_id": generation_id, "document_id": document["id"]},
        )
        bind.execute(
            sa.text(
                "UPDATE ingestion_jobs SET generation_id = :generation_id WHERE document_id = :document_id"
            ),
            {"generation_id": generation_id, "document_id": document["id"]},
        )
        vector_ids = bind.execute(
            sa.text(
                "SELECT vector_id FROM document_chunks WHERE document_id = :document_id AND vector_id IS NOT NULL"
            ),
            {"document_id": document["id"]},
        ).scalars()
        for vector_id in vector_ids:
            bind.execute(
                sa.text(
                    "INSERT INTO generation_vector_manifests (id, generation_id, vector_id) VALUES (:id, :generation_id, :vector_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "generation_id": generation_id,
                    "vector_id": vector_id,
                },
            )
        if generation_status == "active":
            bind.execute(
                sa.text(
                    "UPDATE documents SET active_generation_id = :generation_id WHERE id = :document_id"
                ),
                {"generation_id": generation_id, "document_id": document["id"]},
            )

    op.create_foreign_key(
        "fk_documents_active_generation_id",
        "documents",
        "document_ingestion_generations",
        ["active_generation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_document_chunks_generation_id",
        "document_chunks",
        "document_ingestion_generations",
        ["generation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_generation_id",
        "ingestion_jobs",
        "document_ingestion_generations",
        ["generation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_documents_lifecycle_status", "documents", ["lifecycle_status"], unique=False
    )
    op.create_index(
        "ix_documents_active_generation_id",
        "documents",
        ["active_generation_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_generation_id",
        "document_chunks",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_jobs_generation_id",
        "ingestion_jobs",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        "uq_document_generation_chunk_index",
        "document_chunks",
        ["generation_id", "chunk_index"],
        unique=True,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_active_generation_per_document
        ON document_ingestion_generations (document_id)
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_active_generation_per_document", table_name="document_ingestion_generations"
    )
    op.drop_index("uq_document_generation_chunk_index", table_name="document_chunks")
    op.drop_constraint(
        "fk_ingestion_jobs_generation_id", "ingestion_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_document_chunks_generation_id", "document_chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documents_active_generation_id", "documents", type_="foreignkey"
    )
    op.drop_index("ix_ingestion_jobs_generation_id", table_name="ingestion_jobs")
    op.drop_index("ix_document_chunks_generation_id", table_name="document_chunks")
    op.drop_index("ix_documents_active_generation_id", table_name="documents")
    op.drop_index("ix_documents_lifecycle_status", table_name="documents")
    op.drop_column("ingestion_jobs", "generation_id")
    op.drop_column("document_chunks", "generation_id")
    op.drop_column("documents", "active_generation_id")
    op.drop_column("documents", "lifecycle_status")

    for index_name in (
        "ix_outbox_events_published_at",
        "ix_outbox_events_available_at",
        "ix_outbox_events_topic",
    ):
        op.drop_index(index_name, table_name="outbox_events")
    op.drop_table("outbox_events")

    for index_name in (
        "ix_purge_jobs_next_attempt_at",
        "ix_purge_jobs_status",
        "ix_purge_jobs_generation_id",
        "ix_purge_jobs_document_id",
        "uq_purge_job_idempotency_key",
    ):
        op.drop_index(index_name, table_name="purge_jobs")
    op.drop_table("purge_jobs")

    op.drop_index(
        "ix_generation_vector_manifests_generation_id",
        table_name="generation_vector_manifests",
    )
    op.drop_index("uq_generation_vector_id", table_name="generation_vector_manifests")
    op.drop_table("generation_vector_manifests")

    op.drop_index(
        "ix_document_ingestion_generations_status",
        table_name="document_ingestion_generations",
    )
    op.drop_index(
        "ix_document_ingestion_generations_document_id",
        table_name="document_ingestion_generations",
    )
    op.drop_index(
        "uq_document_generation_number", table_name="document_ingestion_generations"
    )
    op.drop_table("document_ingestion_generations")

    op.execute("DROP TYPE IF EXISTS purge_job_status")
    op.execute("DROP TYPE IF EXISTS document_generation_status")
    op.execute("DROP TYPE IF EXISTS document_lifecycle_status")
