from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
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
    return checks
