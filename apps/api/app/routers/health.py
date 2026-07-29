"""Dependency-independent liveness and dependency-aware readiness endpoints."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.config import get_settings
from app.schemas import INTERNAL_ERROR_RESPONSE

router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    api: str
    redis: str
    database: str
    status: str
    timestamp: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "api": "healthy",
                "redis": "healthy",
                "database": "healthy",
                "status": "healthy",
                "timestamp": "2026-04-08T09:30:00+00:00",
            }
        }
    )


class LivenessResponse(BaseModel):
    status: str
    timestamp: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "timestamp": "2026-07-29T10:00:00+00:00",
            }
        }
    )


class ReadinessResponse(BaseModel):
    api: str
    redis: str
    database: str
    pinecone: str
    generation: str
    status: str
    timestamp: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "api": "healthy",
                "database": "healthy",
                "redis": "healthy",
                "pinecone": "healthy",
                "generation": "healthy",
                "status": "healthy",
                "timestamp": "2026-07-29T10:00:00+00:00",
            }
        }
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


async def _database_status(request: Request) -> str:
    try:
        async with request.app.state.db_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return "unhealthy"
    return "healthy"


async def _redis_status(request: Request) -> str:
    try:
        await request.app.state.redis.ping()
    except Exception:
        return "unhealthy"
    return "healthy"


async def _pinecone_status(request: Request) -> str:
    client = getattr(request.app.state, "pinecone", None)
    if client is None:
        return "unhealthy"
    try:
        # This validates credentials and index visibility without reading vectors.
        await asyncio.to_thread(client.describe_index, settings.pinecone_index_name)
    except Exception:
        return "unhealthy"
    return "healthy"


def _generation_status() -> str:
    # A readiness probe must not spend a generation request or log its credentials.
    # Provider configuration is therefore the safe dependency-availability signal.
    return "healthy" if settings.openrouter_api_key else "unhealthy"


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=200,
    summary="Legacy dependency health check",
    description="Returns API, Redis, and database health for existing monitors.",
    responses={500: INTERNAL_ERROR_RESPONSE},
)
async def health_check(request: Request) -> HealthResponse:
    checks = {
        "api": "healthy",
        "redis": await _redis_status(request),
        "database": await _database_status(request),
        "timestamp": _timestamp(),
    }
    checks["status"] = (
        "healthy"
        if all(checks[key] == "healthy" for key in ("api", "redis", "database"))
        else "degraded"
    )
    return HealthResponse(**checks)


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=200,
    summary="Process liveness check",
    description="Returns healthy while the API process can serve requests; it does not probe dependencies.",
)
async def liveness_check() -> LivenessResponse:
    return LivenessResponse(status="healthy", timestamp=_timestamp())


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=200,
    summary="Dependency readiness check",
    description="Checks Postgres, Redis, Pinecone index access, and generation-provider configuration.",
    responses={503: INTERNAL_ERROR_RESPONSE},
)
async def readiness_check(request: Request, response: Response) -> ReadinessResponse:
    redis_status, database_status, pinecone_status = await asyncio.gather(
        _redis_status(request),
        _database_status(request),
        _pinecone_status(request),
    )
    checks = {
        "api": "healthy",
        "redis": redis_status,
        "database": database_status,
        "pinecone": pinecone_status,
        "generation": _generation_status(),
        "timestamp": _timestamp(),
    }
    is_ready = all(
        checks[key] == "healthy"
        for key in ("api", "redis", "database", "pinecone", "generation")
    )
    checks["status"] = "healthy" if is_ready else "unhealthy"
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(**checks)
