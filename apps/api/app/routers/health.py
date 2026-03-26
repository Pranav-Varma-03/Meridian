from fastapi import APIRouter
from datetime import datetime
import redis.asyncio as redis

from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    checks = {
        "api": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Check Redis connection
    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        checks["redis"] = "healthy"
        await r.close()
    except Exception:
        checks["redis"] = "unhealthy"

    # Overall status
    all_healthy = all(v == "healthy" for k, v in checks.items() if k != "timestamp")
    checks["status"] = "healthy" if all_healthy else "degraded"

    return checks
