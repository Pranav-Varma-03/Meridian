from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.schemas import INTERNAL_ERROR_RESPONSE

router = APIRouter()


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


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=200,
    summary="Service health check",
    description="Returns API, Redis, and database health for monitoring and load balancers.",
    responses={500: INTERNAL_ERROR_RESPONSE},
)
async def health_check(request: Request) -> HealthResponse:
    """Health check endpoint for load balancers and monitoring."""
    checks: dict[str, str] = {
        "api": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "healthy"
    except Exception:
        checks["redis"] = "unhealthy"

    try:
        async with request.app.state.db_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception:
        checks["database"] = "unhealthy"

    all_healthy = all(v == "healthy" for k, v in checks.items() if k != "timestamp")
    checks["status"] = "healthy" if all_healthy else "degraded"
    return HealthResponse(**checks)
