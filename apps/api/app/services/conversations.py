"""Owner-scoped durable conversation operations."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Collection,
    Conversation,
    ConversationMemory,
    ConversationRetrievalScope,
    ConversationScopeEvent,
    Document,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
    Message,
    MessageRole,
    RetrievalScopeMode,
)


class ConversationNotFoundError(Exception):
    """Raised without revealing whether another user owns the conversation."""


class CollectionScopeAccessError(Exception):
    """Raised without disclosing collection ownership or existence."""


@dataclass(frozen=True, slots=True)
class EffectiveRetrievalScope:
    mode: RetrievalScopeMode
    collection_ids: tuple[uuid.UUID, ...]
    version: int

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "collection_ids": [str(value) for value in self.collection_ids],
            "version": self.version,
        }


@dataclass(slots=True)
class ConversationWithMessages:
    conversation: Conversation
    messages: list[Message]
    display_citations: dict[uuid.UUID, dict] = field(default_factory=dict)
    retrieval_scope: EffectiveRetrievalScope | None = None
    scope_events: list[ConversationScopeEvent] = field(default_factory=list)
    has_more_messages: bool = False
    next_before_sequence: int | None = None


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


def _scope_from_row(
    scope: ConversationRetrievalScope | None,
) -> EffectiveRetrievalScope:
    if scope is None:
        return EffectiveRetrievalScope(RetrievalScopeMode.all, (), 0)
    try:
        collection_ids = tuple(uuid.UUID(value) for value in scope.collection_ids)
    except (TypeError, ValueError):
        collection_ids = ()
    return EffectiveRetrievalScope(scope.mode, collection_ids, scope.version)


async def get_effective_retrieval_scope(
    session: AsyncSession, *, conversation_id: uuid.UUID
) -> EffectiveRetrievalScope:
    row = await session.get(ConversationRetrievalScope, conversation_id)
    return _scope_from_row(row)


async def _validate_scope_collections(
    session: AsyncSession, *, user_id: uuid.UUID, collection_ids: tuple[uuid.UUID, ...]
) -> None:
    if not collection_ids:
        return
    result = await session.scalars(
        select(Collection.id).where(
            Collection.user_id == user_id, Collection.id.in_(collection_ids)
        )
    )
    if set(result.all()) != set(collection_ids):
        raise CollectionScopeAccessError("Collection not found")


async def submit_user_turn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    user_id: uuid.UUID,
    content: str,
    requested_scope: tuple[RetrievalScopeMode, tuple[uuid.UUID, ...]] | None,
) -> tuple[Message, EffectiveRetrievalScope]:
    """Persist a user turn and its changed scope as one durable transaction unit."""
    locked = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation.id, Conversation.user_id == user_id)
        .with_for_update()
    )
    if locked is None:
        raise ConversationNotFoundError("Conversation not found")
    scope_row = await session.scalar(
        select(ConversationRetrievalScope)
        .where(ConversationRetrievalScope.conversation_id == locked.id)
        .with_for_update()
    )
    current = _scope_from_row(scope_row)
    target = current
    if requested_scope is not None:
        mode, collection_ids = requested_scope
        if mode == RetrievalScopeMode.collections and not collection_ids:
            raise ValueError("A collection scope requires at least one collection")
        await _validate_scope_collections(
            session, user_id=user_id, collection_ids=collection_ids
        )
        target = EffectiveRetrievalScope(mode, collection_ids, current.version)

    latest_sequence = await session.scalar(
        select(func.max(Message.sequence_number)).where(
            Message.conversation_id == locked.id
        )
    )
    message = Message(
        conversation_id=locked.id,
        sequence_number=int(latest_sequence or 0) + 1,
        role=MessageRole.user,
        content=content,
        citations={},
    )
    session.add(message)
    locked.updated_at = datetime.now(UTC)
    changed = (
        target.mode != current.mode or target.collection_ids != current.collection_ids
    )
    if changed:
        next_version = current.version + 1
        if scope_row is None:
            scope_row = ConversationRetrievalScope(
                conversation_id=locked.id,
                mode=target.mode,
                collection_ids=[str(value) for value in target.collection_ids],
                version=next_version,
            )
            session.add(scope_row)
        else:
            scope_row.mode = target.mode
            scope_row.collection_ids = [str(value) for value in target.collection_ids]
            scope_row.version = next_version
            scope_row.updated_at = datetime.now(UTC)
        target = EffectiveRetrievalScope(
            target.mode, target.collection_ids, next_version
        )
        session.add(
            ConversationScopeEvent(
                conversation_id=locked.id,
                effective_from_sequence=message.sequence_number,
                mode=target.mode,
                collection_ids=[str(value) for value in target.collection_ids],
                scope_version=target.version,
            )
        )
    await session.flush()
    return message, target


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
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_limit: int | None = None,
    before_sequence: int | None = None,
) -> ConversationWithMessages:
    conversation = await get_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    statement = select(Message).where(Message.conversation_id == conversation.id)
    if before_sequence is not None:
        statement = statement.where(Message.sequence_number < before_sequence)
    if message_limit is None:
        messages = await session.scalars(
            statement.order_by(Message.sequence_number.asc())
        )
        message_list = list(messages.all())
        has_more_messages = False
        next_before_sequence = None
    else:
        messages = await session.scalars(
            statement.order_by(Message.sequence_number.desc()).limit(message_limit + 1)
        )
        newest_first = list(messages.all())
        has_more_messages = len(newest_first) > message_limit
        message_list = list(reversed(newest_first[:message_limit]))
        next_before_sequence = (
            message_list[0].sequence_number
            if has_more_messages and message_list
            else None
        )
    scope_events = await session.scalars(
        select(ConversationScopeEvent)
        .where(ConversationScopeEvent.conversation_id == conversation.id)
        .order_by(ConversationScopeEvent.effective_from_sequence.asc())
    )
    return ConversationWithMessages(
        conversation=conversation,
        messages=message_list,
        display_citations=await citation_availability(
            session,
            user_id=user_id,
            messages=message_list,
        ),
        retrieval_scope=await get_effective_retrieval_scope(
            session, conversation_id=conversation.id
        ),
        scope_events=list(scope_events.all()),
        has_more_messages=has_more_messages,
        next_before_sequence=next_before_sequence,
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
