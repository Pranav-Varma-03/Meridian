import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.entities import User
from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    UNSUPPORTED_MEDIA_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.services import documents as document_service
from app.services import ingestion_worker as ingestion_worker_service

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str  # "queued" | "processing" | "ready" | "failed"
    collection_id: str | None = None
    created_at: datetime
    chunk_count: int | None = None
    file_size: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "9f4f8cce-b7b4-4a0a-b529-4f6f5906d5e4",
                "filename": "handbook.pdf",
                "status": "queued",
                "collection_id": "7ecff269-f648-4601-8d97-1c6f0fabf906",
                "created_at": "2026-04-08T09:30:00Z",
                "chunk_count": None,
                "file_size": 204800,
            }
        }
    )


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "documents": [],
                "total": 0,
            }
        }
    )


class DocumentUploadAccepted(BaseModel):
    job_id: str
    filename: str | None
    status: str
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "5f578c6e-a922-4f07-8f13-eb5f62ce17bd",
                "filename": "handbook.pdf",
                "status": "queued",
                "message": "Document queued for processing",
            }
        }
    )


class MessageResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Document deleted successfully",
            }
        }
    )


@router.post(
    "/upload",
    response_model=DocumentUploadAccepted,
    status_code=202,
    summary="Upload document",
    description="Accepts a document upload and enqueues async ingestion.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        415: UNSUPPORTED_MEDIA_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    collection_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Upload a document for processing.
    Supports: PDF, DOCX, TXT (max 10MB)
    Returns immediately with a job_id for async processing.
    """
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="File type not supported. Allowed: PDF, DOCX, TXT",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Max: 10MB")

    try:
        result = await document_service.create_uploaded_document(
            session,
            user_id=current_user.id,
            filename=file.filename or "uploaded-file",
            mime_type=file.content_type,
            file_bytes=contents,
            collection_id=collection_id,
        )
    except document_service.CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        logger.warning(
            "Redis client unavailable; ingestion job not pushed to queue",
            extra={
                "job_id": str(result.job.id),
                "document_id": str(getattr(result.document, "id", "unknown")),
            },
        )
    else:
        try:
            await ingestion_worker_service.enqueue_ingestion_job(
                redis_client,
                queue_key=settings.ingestion_queue_key,
                job_id=result.job.id,
            )
        except Exception:
            logger.exception(
                "Failed to enqueue ingestion job to Redis",
                extra={
                    "job_id": str(result.job.id),
                    "document_id": str(getattr(result.document, "id", "unknown")),
                },
            )

    return DocumentUploadAccepted(
        job_id=str(result.job.id),
        filename=result.document.filename,
        status="queued",
        message="Document queued for processing",
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    status_code=200,
    summary="List documents",
    description="Returns paginated documents for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def list_documents(
    collection_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List all documents for the authenticated user."""
    try:
        documents, total = await document_service.list_documents(
            session,
            user_id=current_user.id,
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )
    except document_service.CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=str(item.document.id),
                filename=item.document.filename,
                status=item.document.status.value,
                collection_id=(
                    str(item.document.collection_id)
                    if item.document.collection_id is not None
                    else None
                ),
                created_at=item.document.created_at,
                chunk_count=item.chunk_count,
                file_size=item.document.file_size,
            )
            for item in documents
        ],
        total=total,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    status_code=200,
    summary="Get document",
    description="Returns document metadata and processing status by id.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get document details and processing status."""
    try:
        result = await document_service.get_document(
            session,
            user_id=current_user.id,
            document_id=document_id,
        )
    except document_service.DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DocumentResponse(
        id=str(result.document.id),
        filename=result.document.filename,
        status=result.document.status.value,
        collection_id=(
            str(result.document.collection_id)
            if result.document.collection_id is not None
            else None
        ),
        created_at=result.document.created_at,
        chunk_count=result.chunk_count,
        file_size=result.document.file_size,
    )


@router.delete(
    "/{document_id}",
    response_model=MessageResponse,
    status_code=200,
    summary="Delete document",
    description="Deletes document data and returns a success message.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a document and all associated chunks/embeddings.
    Also removes from vector store and file storage.
    """
    try:
        await document_service.delete_document(
            session,
            user_id=current_user.id,
            document_id=document_id,
        )
    except document_service.DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return MessageResponse(message="Document deleted successfully")
