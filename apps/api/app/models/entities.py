import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IngestionStatus(enum.StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DocumentLifecycleStatus(enum.StrEnum):
    active = "active"
    deleting = "deleting"
    deleted = "deleted"


class GenerationStatus(enum.StrEnum):
    pending = "pending"
    active = "active"
    superseded = "superseded"
    failed = "failed"
    purged = "purged"


class ReingestionReason(enum.StrEnum):
    """Supported, user-visible reasons for an explicit document re-ingestion."""

    manual_repair = "manual_repair"
    model_migration = "model_migration"
    chunking_change = "chunking_change"


class PurgeJobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    retryable = "retryable"
    complete = "complete"
    terminal_failed = "terminal_failed"


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class RetrievalScopeMode(enum.StrEnum):
    all = "all"
    collections = "collections"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auth_subject: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    collections: Mapped[list["Collection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="collections")
    documents: Mapped[list["Document"]] = relationship(back_populates="collection")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "uq_documents_user_file_hash",
            "user_id",
            "file_hash",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_status"),
        default=IngestionStatus.queued,
        nullable=False,
    )
    lifecycle_status: Mapped[DocumentLifecycleStatus] = mapped_column(
        Enum(DocumentLifecycleStatus, name="document_lifecycle_status"),
        default=DocumentLifecycleStatus.active,
        nullable=False,
        index=True,
    )
    active_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="documents")
    collection: Mapped[Collection | None] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    parent_windows: Mapped[list["DocumentParentWindow"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    generations: Mapped[list["DocumentIngestionGeneration"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    purge_jobs: Mapped[list["PurgeJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_parent_windows.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    next_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_path: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lexical_search: Mapped[object | None] = mapped_column(TSVECTOR, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
    parent: Mapped["DocumentParentWindow | None"] = relationship(
        back_populates="children", foreign_keys=[parent_id]
    )
    previous_chunk: Mapped["DocumentChunk | None"] = relationship(
        foreign_keys=[previous_chunk_id], remote_side=[id], uselist=False
    )
    next_chunk: Mapped["DocumentChunk | None"] = relationship(
        foreign_keys=[next_chunk_id], remote_side=[id], uselist=False
    )


class DocumentParentWindow(Base):
    __tablename__ = "document_parent_windows"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "generation_id",
            "parent_index",
            name="uq_parent_window_generation_order",
        ),
        Index(
            "ix_parent_windows_document_generation_order",
            "document_id",
            "generation_id",
            "parent_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_ingestion_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="parent_windows")
    generation: Mapped["DocumentIngestionGeneration"] = relationship(
        back_populates="parent_windows"
    )
    children: Mapped[list[DocumentChunk]] = relationship(
        back_populates="parent", foreign_keys="DocumentChunk.parent_id"
    )


class DocumentIngestionGeneration(Base):
    __tablename__ = "document_ingestion_generations"
    __table_args__ = (
        Index(
            "uq_document_generation_number",
            "document_id",
            "generation_number",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, name="document_generation_status"),
        nullable=False,
        default=GenerationStatus.pending,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_json: Mapped[dict] = mapped_column(
        "configuration", JSONB, default=dict, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="generations")
    parent_windows: Mapped[list[DocumentParentWindow]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )
    vector_manifest: Mapped[list["GenerationVectorManifest"]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )
    purge_jobs: Mapped[list["PurgeJob"]] = relationship(back_populates="generation")


class GenerationVectorManifest(Base):
    __tablename__ = "generation_vector_manifests"
    __table_args__ = (
        Index("uq_generation_vector_id", "generation_id", "vector_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_ingestion_generations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vector_id: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    generation: Mapped[DocumentIngestionGeneration] = relationship(
        back_populates="vector_manifest"
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_job_status"),
        default=IngestionStatus.queued,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="ingestion_jobs")


class PurgeJob(Base):
    __tablename__ = "purge_jobs"
    __table_args__ = (
        Index("uq_purge_job_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_ingestion_generations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[PurgeJobStatus] = mapped_column(
        Enum(PurgeJobStatus, name="purge_job_status"),
        nullable=False,
        default=PurgeJobStatus.queued,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="purge_jobs")
    generation: Mapped[DocumentIngestionGeneration | None] = relationship(
        back_populates="purge_jobs"
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column("payload", JSONB, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    memory: Mapped["ConversationMemory | None"] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", uselist=False
    )
    retrieval_scope: Mapped["ConversationRetrievalScope | None"] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", uselist=False
    )
    scope_events: Mapped[list["ConversationScopeEvent"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationRetrievalScope(Base):
    __tablename__ = "conversation_retrieval_scopes"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[RetrievalScopeMode] = mapped_column(
        Enum(RetrievalScopeMode, name="retrieval_scope_mode"), nullable=False
    )
    collection_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="retrieval_scope")


class ConversationScopeEvent(Base):
    __tablename__ = "conversation_scope_events"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "effective_from_sequence",
            name="uq_conversation_scope_event_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    effective_from_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[RetrievalScopeMode] = mapped_column(
        Enum(RetrievalScopeMode, name="retrieval_scope_mode"), nullable=False
    )
    collection_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    scope_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="scope_events")


class ConversationMemory(Base):
    __tablename__ = "conversation_memories"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary_json: Mapped[dict] = mapped_column(
        "summary", JSONB, default=dict, nullable=False
    )
    summary_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summarized_through_sequence: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="memory")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_messages_conversation_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
