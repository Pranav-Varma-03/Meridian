import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)

router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    collection_ids: list[str] | None = None  # If None, search all collections

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Summarize the onboarding policy",
                "conversation_id": None,
                "collection_ids": ["7ecff269-f648-4601-8d97-1c6f0fabf906"],
            }
        }
    )


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    conversation_id: str


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversations": [],
                "total": 0,
            }
        }
    )


class ConversationMessage(BaseModel):
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    messages: list[ConversationMessage]


class MessageResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"message": "Conversation deleted"}}
    )


@router.post(
    "",
    status_code=200,
    summary="Stream chat response",
    description=(
        "Streams RAG responses using Server-Sent Events (SSE). "
        "Event payloads include `text`, `sources`, and `done` chunks."
    ),
    responses={
        200: {
            "description": "SSE stream",
            "content": {
                "text/event-stream": {
                    "example": (
                        'data: {"type":"text","content":"Hello"}\\n\\n'
                        'data: {"type":"done"}\\n\\n'
                    )
                }
            },
        },
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def chat(request: ChatRequest):
    """
    RAG chat endpoint with streaming response.

    Flow:
    1. Load conversation history (if conversation_id provided)
    2. Route query to relevant collections
    3. Retrieve relevant chunks
    4. Generate streaming response
    5. Save conversation turn
    """

    async def generate():
        # TODO: Implement full RAG pipeline
        # For now, return a placeholder streaming response
        chunks = [
            {"type": "text", "content": "This is a "},
            {"type": "text", "content": "streaming "},
            {"type": "text", "content": "response "},
            {"type": "text", "content": "placeholder."},
            {
                "type": "sources",
                "content": [],  # Sources will go here
            },
            {"type": "done"},
        ]
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    status_code=200,
    summary="List conversations",
    description="Returns paginated conversation history for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def list_conversations(limit: int = 20, offset: int = 0):
    """List conversation history for the authenticated user."""
    # TODO: Fetch from Redis/DB
    return ConversationListResponse(conversations=[], total=0)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    status_code=200,
    summary="Get conversation",
    description="Returns full message history for a conversation.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def get_conversation(conversation_id: str):
    """Get full conversation history."""
    # TODO: Fetch from Redis/DB
    raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete(
    "/conversations/{conversation_id}",
    response_model=MessageResponse,
    status_code=200,
    summary="Delete conversation",
    description="Deletes one conversation and its messages.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    # TODO: Delete from Redis/DB
    return MessageResponse(message="Conversation deleted")
