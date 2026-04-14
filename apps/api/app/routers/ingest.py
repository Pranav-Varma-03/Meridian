import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.entities import User
from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.services import documents as document_service
from app.services import ingestion_worker as ingestion_worker_service

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


class IngestRequest(BaseModel):
    document_id: uuid.UUID

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_id": "9f4f8cce-b7b4-4a0a-b529-4f6f5906d5e4",
            }
        }
    )


class IngestAcceptedResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    message: str
    reused_existing_job: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "5f578c6e-a922-4f07-8f13-eb5f62ce17bd",
                "document_id": "9f4f8cce-b7b4-4a0a-b529-4f6f5906d5e4",
                "status": "queued",
                "message": "Ingestion job queued",
                "reused_existing_job": False,
            }
        }
    )


class IngestionJobResponse(BaseModel):
    id: str
    document_id: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "5f578c6e-a922-4f07-8f13-eb5f62ce17bd",
                "document_id": "9f4f8cce-b7b4-4a0a-b529-4f6f5906d5e4",
                "status": "queued",
                "attempts": 0,
                "error": None,
                "started_at": None,
                "completed_at": None,
                "created_at": "2026-04-10T05:00:00Z",
            }
        }
    )


@router.post(
    "",
    response_model=IngestAcceptedResponse,
    status_code=202,
    summary="Queue ingestion job",
    description="Creates a queued ingestion job for an existing user document.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def queue_ingestion(
    payload: IngestRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await document_service.create_ingestion_job(
            session,
            user_id=current_user.id,
            document_id=payload.document_id,
        )
    except document_service.DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result.created_new_job:
        try:
            await ingestion_worker_service.enqueue_ingestion_job(
                request.app.state.redis,
                queue_key=settings.ingestion_queue_key,
                job_id=result.job.id,
            )
        except Exception:
            logger.exception(
                "Failed to enqueue ingestion job to Redis",
                extra={
                    "job_id": str(result.job.id),
                    "document_id": str(result.document.id),
                },
            )

    return IngestAcceptedResponse(
        job_id=str(result.job.id),
        document_id=str(result.document.id),
        status=result.job.status.value,
        message=(
            "Existing active ingestion job returned"
            if not result.created_new_job
            else "Ingestion job queued"
        ),
        reused_existing_job=not result.created_new_job,
    )


@router.get(
    "/{job_id}",
    response_model=IngestionJobResponse,
    status_code=200,
    summary="Get ingestion job status",
    description="Returns ingestion job status for a user-owned document.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def get_ingestion_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await document_service.get_ingestion_job(
            session,
            user_id=current_user.id,
            job_id=job_id,
        )
    except document_service.IngestionJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return IngestionJobResponse(
        id=str(result.job.id),
        document_id=str(result.document.id),
        status=result.job.status.value,
        attempts=result.job.attempts,
        error=result.job.error,
        started_at=result.job.started_at,
        completed_at=result.job.completed_at,
        created_at=result.job.created_at,
    )
