import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Collection,
    Document,
    DocumentChunk,
    IngestionJob,
    IngestionStatus,
)
from app.services import document_processor


class DocumentNotFoundError(Exception):
    """Raised when a document is not found for the current user."""


class CollectionNotFoundError(Exception):
    """Raised when the requested collection is not found for the current user."""


class IngestionJobNotFoundError(Exception):
    """Raised when an ingestion job is not found for the current user."""


@dataclass(slots=True)
class DocumentWithCount:
    document: Document
    chunk_count: int


@dataclass(slots=True)
class UploadResult:
    document: Document
    job: IngestionJob
    deduplicated: bool = False
    enqueue_job: bool = True


@dataclass(slots=True)
class IngestionJobWithDocument:
    job: IngestionJob
    document: Document
    created_new_job: bool = True


async def create_uploaded_document(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
    collection_id: uuid.UUID | None,
) -> UploadResult:
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    async def _existing_upload_result() -> UploadResult | None:
        existing_document = await session.scalar(
            select(Document).where(
                Document.user_id == user_id,
                Document.file_hash == file_hash,
            )
        )
        if existing_document is None:
            return None

        active_job = await session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == existing_document.id,
                IngestionJob.status.in_(
                    [
                        IngestionStatus.queued,
                        IngestionStatus.processing,
                    ]
                ),
            )
            .order_by(IngestionJob.created_at.desc())
        )
        if active_job is not None:
            return UploadResult(
                document=existing_document,
                job=active_job,
                deduplicated=True,
                enqueue_job=False,
            )

        latest_job = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.document_id == existing_document.id)
            .order_by(IngestionJob.created_at.desc())
        )
        if latest_job is not None:
            return UploadResult(
                document=existing_document,
                job=latest_job,
                deduplicated=True,
                enqueue_job=False,
            )

        # Legacy/self-heal fallback for documents without any recorded ingestion job.
        existing_document.status = IngestionStatus.queued
        repair_job = IngestionJob(
            document_id=existing_document.id,
            status=IngestionStatus.queued,
            attempts=0,
        )
        session.add(repair_job)
        await session.commit()
        await session.refresh(existing_document)
        await session.refresh(repair_job)
        return UploadResult(
            document=existing_document,
            job=repair_job,
            deduplicated=True,
            enqueue_job=True,
        )

    if collection_id is not None:
        collection_exists = await session.scalar(
            select(Collection.id).where(
                Collection.id == collection_id,
                Collection.user_id == user_id,
            )
        )
        if collection_exists is None:
            raise CollectionNotFoundError("Collection not found")

    existing_result = await _existing_upload_result()
    if existing_result is not None:
        return existing_result

    document_id = uuid.uuid4()
    storage_path = document_processor.save_uploaded_file(
        document_id=document_id,
        filename=filename,
        file_bytes=file_bytes,
    )

    document = Document(
        id=document_id,
        user_id=user_id,
        collection_id=collection_id,
        filename=filename,
        file_hash=file_hash,
        file_size=len(file_bytes),
        mime_type=mime_type,
        status=IngestionStatus.queued,
        metadata_json={
            "storage_path": storage_path,
        },
    )
    session.add(document)
    await session.flush()

    job = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.queued,
        attempts=0,
    )
    session.add(job)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        conflict_result = await _existing_upload_result()
        if conflict_result is not None:
            return conflict_result
        raise
    await session.refresh(document)
    await session.refresh(job)

    return UploadResult(
        document=document,
        job=job,
        deduplicated=False,
        enqueue_job=True,
    )


async def list_documents(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[DocumentWithCount], int]:
    if collection_id is not None:
        collection_exists = await session.scalar(
            select(Collection.id).where(
                Collection.id == collection_id,
                Collection.user_id == user_id,
            )
        )
        if collection_exists is None:
            raise CollectionNotFoundError("Collection not found")

    filters = [Document.user_id == user_id]
    if collection_id is not None:
        filters.append(Document.collection_id == collection_id)

    total = await session.scalar(select(func.count(Document.id)).where(*filters))
    total_count = int(total or 0)

    result = await session.execute(
        select(Document, func.count(DocumentChunk.id).label("chunk_count"))
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(*filters)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    documents = [
        DocumentWithCount(document=row[0], chunk_count=int(row[1] or 0)) for row in rows
    ]
    return documents, total_count


async def get_document(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> DocumentWithCount:
    result = await session.execute(
        select(Document, func.count(DocumentChunk.id).label("chunk_count"))
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(
            Document.user_id == user_id,
            Document.id == document_id,
        )
        .group_by(Document.id)
    )
    row = result.first()
    if row is None:
        raise DocumentNotFoundError("Document not found")

    return DocumentWithCount(document=row[0], chunk_count=int(row[1] or 0))


async def delete_document(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    document = await session.scalar(
        select(Document).where(
            Document.user_id == user_id,
            Document.id == document_id,
        )
    )
    if document is None:
        raise DocumentNotFoundError("Document not found")

    await session.delete(document)
    await session.commit()


async def create_ingestion_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> IngestionJobWithDocument:
    document = await session.scalar(
        select(Document).where(
            Document.user_id == user_id,
            Document.id == document_id,
        )
    )
    if document is None:
        raise DocumentNotFoundError("Document not found")

    active_job = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.status.in_(
                [
                    IngestionStatus.queued,
                    IngestionStatus.processing,
                ]
            ),
        )
        .order_by(IngestionJob.created_at.desc())
    )
    if active_job is not None:
        return IngestionJobWithDocument(
            job=active_job,
            document=document,
            created_new_job=False,
        )

    document.status = IngestionStatus.queued

    job = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.queued,
        attempts=0,
    )
    session.add(job)

    await session.commit()
    await session.refresh(document)
    await session.refresh(job)

    return IngestionJobWithDocument(job=job, document=document, created_new_job=True)


async def get_ingestion_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> IngestionJobWithDocument:
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(
            IngestionJob.id == job_id,
            Document.user_id == user_id,
        )
    )
    row = result.first()
    if row is None:
        raise IngestionJobNotFoundError("Ingestion job not found")

    return IngestionJobWithDocument(job=row[0], document=row[1])
