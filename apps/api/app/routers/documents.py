from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid

router = APIRouter()


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str  # "queued" | "processing" | "ready" | "failed"
    collection_id: Optional[str] = None
    created_at: datetime
    chunk_count: Optional[int] = None
    file_size: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


@router.post("/upload", response_model=dict)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: Optional[str] = None,
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
            detail=f"File type not supported. Allowed: PDF, DOCX, TXT",
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


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    collection_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all documents for the authenticated user."""
    # TODO: Fetch from database with user_id filter
    return DocumentListResponse(documents=[], total=0)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str):
    """Get document details and processing status."""
    # TODO: Fetch from database
    raise HTTPException(status_code=404, detail="Document not found")


@router.delete("/{document_id}")
async def delete_document(document_id: str):
    """
    Delete a document and all associated chunks/embeddings.
    Also removes from vector store and file storage.
    """
    # TODO: Delete from DB (cascades to chunks)
    # TODO: Delete from Pinecone
    # TODO: Delete from S3
    return {"message": "Document deleted successfully"}
