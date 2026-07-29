import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.observability import lifecycle_event
from app.core.rate_limits import require_rate_limit
from app.models.entities import MessageRole, RetrievalScopeMode, User
from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    SERVICE_UNAVAILABLE_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.services import (
    chat_generation,
    conversation_context,
    conversations,
    retrieval,
)

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


class RetrievalScopeRequest(BaseModel):
    mode: Literal["all", "collections"]
    collection_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class RetrievalScopeResponse(BaseModel):
    mode: Literal["all", "collections"]
    collection_ids: list[str]
    version: int


class ConversationScopeEventResponse(RetrievalScopeResponse):
    effective_from_sequence: int


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=12000)
    conversation_id: uuid.UUID | None = None
    collection_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    retrieval_scope: RetrievalScopeRequest | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Summarize the onboarding policy",
                "conversation_id": "152dc37c-de00-47d0-a47c-3a2f7804cbb1",
                "collection_ids": ["7ecff269-f648-4601-8d97-1c6f0fabf906"],
            }
        }
    )


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    updated_at: datetime
    retrieval_scope: RetrievalScopeResponse


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int


class ConversationMessage(BaseModel):
    id: str
    role: str
    content: str
    citations: dict
    created_at: datetime


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    messages: list[ConversationMessage]
    retrieval_scope: RetrievalScopeResponse
    scope_events: list[ConversationScopeEventResponse]


class MessageResponse(BaseModel):
    message: str


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _message_response(message, *, citations: dict | None = None) -> ConversationMessage:
    return ConversationMessage(
        id=str(message.id),
        role=message.role.value,
        content=message.content,
        citations=citations if citations is not None else message.citations or {},
        created_at=message.created_at,
    )


def _scope_response(
    scope: conversations.EffectiveRetrievalScope,
) -> RetrievalScopeResponse:
    return RetrievalScopeResponse(
        mode=scope.mode.value,
        collection_ids=[str(value) for value in scope.collection_ids],
        version=scope.version,
    )


def _normalized_requested_scope(
    payload: ChatRequest,
) -> tuple[RetrievalScopeMode, tuple[uuid.UUID, ...]] | None:
    has_new = "retrieval_scope" in payload.model_fields_set
    has_legacy = "collection_ids" in payload.model_fields_set

    def normalize(
        mode: str, values: list[uuid.UUID]
    ) -> tuple[RetrievalScopeMode, tuple[uuid.UUID, ...]]:
        if len(set(values)) != len(values):
            raise HTTPException(status_code=422, detail="Collection IDs must be unique")
        # Pinecone's $in filter is set-like. Store/compare a stable canonical order so
        # matching new and legacy fields do not conflict merely because callers order
        # the same collection IDs differently.
        unique = tuple(sorted(values, key=str))
        if mode == "all":
            if unique:
                raise HTTPException(
                    status_code=422, detail="All scope cannot include collection IDs"
                )
            return RetrievalScopeMode.all, ()
        if not unique:
            raise HTTPException(
                status_code=422, detail="Collection scope requires collection IDs"
            )
        return RetrievalScopeMode.collections, unique

    new_scope = None
    if has_new:
        if payload.retrieval_scope is None:
            raise HTTPException(
                status_code=422, detail="retrieval_scope cannot be null"
            )
        new_scope = normalize(
            payload.retrieval_scope.mode, payload.retrieval_scope.collection_ids
        )
    legacy_scope = None
    if has_legacy:
        legacy_ids = payload.collection_ids or []
        legacy_scope = normalize("collections" if legacy_ids else "all", legacy_ids)
    if new_scope is not None and legacy_scope is not None and new_scope != legacy_scope:
        raise HTTPException(
            status_code=422, detail="Conflicting retrieval scope fields"
        )
    return new_scope if new_scope is not None else legacy_scope


@router.post(
    "",
    status_code=200,
    summary="Stream grounded chat response",
    description=(
        "Authenticated POST-SSE chat. The stream emits zero or more `text` events, "
        "one `sources` event, and a terminal `done` event."
    ),
    responses={
        200: {
            "description": "SSE stream",
            "content": {
                "text/event-stream": {
                    "example": (
                        'data: {"type":"text","content":"Hello"}\\n\\n'
                        'data: {"type":"sources","content":[]}\\n\\n'
                        'data: {"type":"done","conversation_id":"..."}\\n\\n'
                    )
                }
            },
        },
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        429: {"description": "Rate limit exceeded"},
        503: SERVICE_UNAVAILABLE_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def chat(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    _rate_limit: None = Depends(require_rate_limit("chat")),
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieve lifecycle-valid PDF evidence and stream a grounded response."""
    requested_scope = _normalized_requested_scope(payload)
    try:
        conversation = await conversations.create_or_get_conversation(
            session,
            user_id=current_user.id,
            conversation_id=payload.conversation_id,
            initial_query=payload.query,
        )
        history = await conversations.load_recent_history(
            session,
            conversation_id=conversation.id,
            limit=settings.chat_history_max_messages,
        )
        memory = await conversations.get_memory(
            session, user_id=current_user.id, conversation_id=conversation.id
        )
        _user_message, effective_scope = await conversations.submit_user_turn(
            session,
            conversation=conversation,
            user_id=current_user.id,
            content=payload.query.strip(),
            requested_scope=requested_scope,
        )
        await session.commit()
    except conversations.ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except conversations.CollectionScopeAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pinecone_client = getattr(request.app.state, "pinecone", None)
    if pinecone_client is None:
        raise HTTPException(
            status_code=503, detail="Retrieval is temporarily unavailable"
        )
    # OpenAI is retained only for optional OpenAI embeddings during retrieval.
    openai_client = (
        AsyncOpenAI(api_key=settings.openai_api_key)
        if settings.openai_api_key
        else None
    )
    openrouter_client = (
        AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        if settings.openrouter_api_key
        else None
    )
    rewrite = await chat_generation.rewrite_retrieval_query(
        client=openrouter_client,
        settings=settings,
        query=payload.query,
        history=history,
        summary=memory.summary_json if memory is not None else None,
    )
    if rewrite.needs_clarification:
        sources = []
    else:
        try:
            sources = await retrieval.retrieve_sources(
                session,
                settings=settings,
                pinecone_client=pinecone_client,
                query=rewrite.query,
                user_id=current_user.id,
                collection_ids=list(effective_scope.collection_ids) or None,
                openai_client=openai_client,
            )
        except retrieval.CollectionAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (retrieval.RetrievalUnavailableError, ValueError) as exc:
            raise HTTPException(
                status_code=503, detail="Retrieval is temporarily unavailable"
            ) from exc

    assembly = (
        chat_generation.build_messages(
            query=payload.query,
            history=history,
            summary=memory.summary_json if memory is not None else None,
            sources=sources,
            settings=settings,
        )
        if sources
        else None
    )
    included_sources = assembly.included_sources if assembly is not None else []
    normalized_sources = [source.citation() for source in included_sources]
    logger.info(
        "chat_context_selected",
        extra={
            "request_id": getattr(request.state, "request_id", "unknown"),
            "conversation_id": str(conversation.id),
            "retrieved_source_count": len(sources),
            "included_source_count": len(included_sources),
            "included_history_count": len(assembly.included_history)
            if assembly is not None
            else 0,
            "included_summary": bool(assembly and assembly.included_summary),
            "input_budget_tokens": assembly.input_budget_tokens
            if assembly is not None
            else 0,
            "source_tokens": assembly.source_tokens if assembly is not None else 0,
            "history_tokens": assembly.history_tokens if assembly is not None else 0,
            "summary_tokens": assembly.summary_tokens if assembly is not None else 0,
            "rewrite_requested_clarification": rewrite.needs_clarification,
        },
    )
    lifecycle_event(
        logger,
        "chat_retrieval_completed",
        request_id=getattr(request.state, "request_id", "unknown"),
        conversation_id=str(conversation.id),
        retrieval_scope_mode=effective_scope.mode.value,
        retrieval_scope_version=effective_scope.version,
        retrieved_source_count=len(sources),
        included_source_count=len(included_sources),
    )

    async def generate() -> AsyncIterator[str]:
        done_event = {
            "type": "done",
            "conversation_id": str(conversation.id),
            "retrieval_scope": _scope_response(effective_scope).model_dump(),
        }
        if rewrite.needs_clarification or not included_sources:
            answer = (
                chat_generation.CLARIFICATION_ANSWER
                if rewrite.needs_clarification
                else chat_generation.INSUFFICIENT_CONTEXT_ANSWER
            )
            await conversations.add_message(
                session,
                conversation=conversation,
                role=MessageRole.assistant,
                content=answer,
                citations={"sources": []},
            )
            await session.commit()
            yield _sse({"type": "text", "content": answer})
            yield _sse({"type": "sources", "content": []})
            yield _sse(done_event)
            return

        answer_parts: list[str] = []
        try:
            async for text in chat_generation.stream_grounded_answer(
                client=openrouter_client,
                settings=settings,
                prompt_messages=assembly.messages,
            ):
                answer_parts.append(text)
                yield _sse({"type": "text", "content": text})
        except chat_generation.GenerationUnavailableError:
            # SSE has already started. Keep the failure safe and do not persist a
            # partial assistant message as durable conversation history.
            yield _sse(
                {
                    "type": "error",
                    "message": "Chat generation is temporarily unavailable",
                }
            )
            yield _sse(done_event)
            return

        answer = "".join(answer_parts).strip()
        if not answer:
            yield _sse(
                {"type": "error", "message": "Chat generation returned no answer"}
            )
            yield _sse(done_event)
            return
        await conversations.add_message(
            session,
            conversation=conversation,
            role=MessageRole.assistant,
            content=answer,
            citations={"sources": normalized_sources},
        )
        await conversation_context.update_rolling_summary(
            session,
            conversation=conversation,
            client=openrouter_client,
            settings=settings,
        )
        await session.commit()
        lifecycle_event(
            logger,
            "chat_generation_completed",
            request_id=getattr(request.state, "request_id", "unknown"),
            conversation_id=str(conversation.id),
            retrieval_scope_mode=effective_scope.mode.value,
            retrieval_scope_version=effective_scope.version,
            outcome="success",
        )
        yield _sse({"type": "sources", "content": normalized_sources})
        yield _sse(done_event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    status_code=200,
    summary="List conversations",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationListResponse:
    items, total = await conversations.list_conversations(
        session, user_id=current_user.id, limit=limit, offset=offset
    )
    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                id=str(item.id),
                title=item.title,
                updated_at=item.updated_at,
                retrieval_scope=_scope_response(
                    await conversations.get_effective_retrieval_scope(
                        session, conversation_id=item.id
                    )
                ),
            )
            for item in items
        ],
        total=total,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    status_code=200,
    summary="Get conversation",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    try:
        result = await conversations.get_conversation_with_messages(
            session, user_id=current_user.id, conversation_id=conversation_id
        )
    except conversations.ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConversationResponse(
        id=str(result.conversation.id),
        title=result.conversation.title,
        messages=[
            _message_response(
                message,
                citations=getattr(result, "display_citations", {}).get(message.id),
            )
            for message in result.messages
        ],
        retrieval_scope=_scope_response(result.retrieval_scope),
        scope_events=[
            ConversationScopeEventResponse(
                mode=event.mode.value,
                collection_ids=list(event.collection_ids),
                version=event.scope_version,
                effective_from_sequence=event.effective_from_sequence,
            )
            for event in result.scope_events
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=MessageResponse,
    status_code=200,
    summary="Delete conversation",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    try:
        await conversations.delete_conversation(
            session, user_id=current_user.id, conversation_id=conversation_id
        )
    except conversations.ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MessageResponse(message="Conversation deleted")
