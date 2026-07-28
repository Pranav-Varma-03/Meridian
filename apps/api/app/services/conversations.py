"""Owner-scoped durable conversation operations."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Conversation,
    ConversationMemory,
    Document,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
    Message,
    MessageRole,
)


class ConversationNotFoundError(Exception):
    """Raised without revealing whether another user owns the conversation."""


@dataclass(slots=True)
class ConversationWithMessages:
    conversation: Conversation
    messages: list[Message]
    display_citations: dict[uuid.UUID, dict] = field(default_factory=dict)


async def get_conversation(
    session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    return conversation


async def create_or_get_conversation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    initial_query: str,
) -> Conversation:
    if conversation_id is not None:
        return await get_conversation(
            session, user_id=user_id, conversation_id=conversation_id
        )
    conversation = Conversation(
        user_id=user_id, title=initial_query.strip()[:255] or None
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def add_message(
    session: AsyncSession,
    *,
    conversation: Conversation,
    role: MessageRole,
    content: str,
    citations: dict | None = None,
) -> Message:
    # Serialise sequence allocation per conversation. This removes timestamp-tie
    # ambiguity and prevents two concurrent streams from receiving the same order.
    locked_conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation.id).with_for_update()
    )
    if locked_conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    latest_sequence = await session.scalar(
        select(func.max(Message.sequence_number)).where(
            Message.conversation_id == conversation.id
        )
    )
    message = Message(
        conversation_id=conversation.id,
        sequence_number=int(latest_sequence or 0) + 1,
        role=role,
        content=content,
        citations=citations or {},
    )
    session.add(message)
    locked_conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return message


async def get_or_create_memory(
    session: AsyncSession, *, conversation_id: uuid.UUID
) -> ConversationMemory:
    memory = await session.scalar(
        select(ConversationMemory)
        .where(ConversationMemory.conversation_id == conversation_id)
        .with_for_update()
    )
    if memory is not None:
        return memory
    memory = ConversationMemory(conversation_id=conversation_id)
    session.add(memory)
    await session.flush()
    return memory


async def get_memory(
    session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationMemory | None:
    return await session.scalar(
        select(ConversationMemory)
        .join(Conversation)
        .where(
            ConversationMemory.conversation_id == conversation_id,
            Conversation.user_id == user_id,
        )
    )


async def list_conversations(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    total = await session.scalar(
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all()), int(total or 0)


async def get_conversation_with_messages(
    session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationWithMessages:
    conversation = await get_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    messages = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.sequence_number.asc())
    )
    message_list = list(messages.all())
    return ConversationWithMessages(
        conversation=conversation,
        messages=message_list,
        display_citations=await citation_availability(
            session,
            user_id=user_id,
            messages=message_list,
        ),
    )


async def load_recent_history(
    session: AsyncSession, *, conversation_id: uuid.UUID, limit: int
) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sequence_number.desc())
        .limit(limit)
    )
    return list(reversed(list(result.all())))


async def load_messages_after_sequence(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    after_sequence: int,
    through_sequence: int,
) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sequence_number > after_sequence,
            Message.sequence_number <= through_sequence,
        )
        .order_by(Message.sequence_number.asc())
    )
    return list(result.all())


async def citation_availability(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    messages: list[Message],
) -> dict[uuid.UUID, dict]:
    """Return historical citation snapshots annotated without changing stored JSON."""
    identities: set[tuple[uuid.UUID, int]] = set()
    for message in messages:
        for source in (message.citations or {}).get("sources", []):
            if not isinstance(source, dict):
                continue
            try:
                identities.add(
                    (uuid.UUID(str(source["document_id"])), int(source["generation"]))
                )
            except (KeyError, TypeError, ValueError):
                continue
    active: set[tuple[uuid.UUID, int]] = set()
    if identities:
        document_ids = [document_id for document_id, _ in identities]
        result = await session.execute(
            select(Document.id, DocumentIngestionGeneration.generation_number)
            .join(
                DocumentIngestionGeneration,
                DocumentIngestionGeneration.id == Document.active_generation_id,
            )
            .where(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
                Document.lifecycle_status == DocumentLifecycleStatus.active,
                DocumentIngestionGeneration.status == GenerationStatus.active,
            )
        )
        active = set(result.all())

    annotated: dict[uuid.UUID, dict] = {}
    for message in messages:
        original = message.citations or {}
        sources: list[dict] = []
        for source in original.get("sources", []):
            if not isinstance(source, dict):
                continue
            rendered = dict(source)
            try:
                identity = (
                    uuid.UUID(str(rendered["document_id"])),
                    int(rendered["generation"]),
                )
            except (KeyError, TypeError, ValueError):
                identity = None
            rendered["available"] = identity in active
            if identity is not None and identity not in active:
                rendered["unavailable_reason"] = "source_unavailable"
            sources.append(rendered)
        annotated[message.id] = {**original, "sources": sources}
    return annotated


async def delete_conversation(
    session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    await session.delete(conversation)
    await session.commit()
