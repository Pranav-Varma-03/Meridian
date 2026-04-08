import uuid
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    UNSUPPORTED_MEDIA_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)

router = APIRouter()


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
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        415: UNSUPPORTED_MEDIA_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: str | None = None,
):
    """
    Upload a document for processing.
    Supports: PDF, DOCX, TXT (max 10MB)
    Returns immediately with a job_id for async processing.
    """
    # Validate file type
    allowed_types = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="File type not supported. Allowed: PDF, DOCX, TXT",
        )

    # Validate file size (10MB)
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max: 10MB")

    # Generate job ID and queue for processing
    job_id = str(uuid.uuid4())

    # TODO: Queue document for async processing via BullMQ
    # TODO: Upload raw file to S3
    # TODO: Create document record in DB

    return {
        "job_id": job_id,
        "filename": file.filename,
        "status": "queued",
        "message": "Document queued for processing",
    }


@router.get(
    "",
    response_model=DocumentListResponse,
    status_code=200,
    summary="List documents",
    description="Returns paginated documents for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def list_documents(
    collection_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all documents for the authenticated user."""
    # TODO: Fetch from database with user_id filter
    return DocumentListResponse(documents=[], total=0)


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
async def get_document(document_id: str):
    """Get document details and processing status."""
    # TODO: Fetch from database
    raise HTTPException(status_code=404, detail="Document not found")


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
async def delete_document(document_id: str):
    """
    Delete a document and all associated chunks/embeddings.
    Also removes from vector store and file storage.
    """
    # TODO: Delete from DB (cascades to chunks)
    # TODO: Delete from Pinecone
    # TODO: Delete from S3
    return {"message": "Document deleted successfully"}
