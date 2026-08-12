"""Redis-coordinated, identity-aware limits for expensive API routes."""

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from redis.exceptions import RedisError

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.observability import DependencySpan, lifecycle_event
from app.models.entities import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimit:
    route: str
    maximum: int
    window_seconds: int


def _limit_for(route: str) -> RateLimit:
    settings = get_settings()
    if route == "chat":
        return RateLimit(
            route,
            settings.chat_rate_limit_requests,
            settings.chat_rate_limit_window_seconds,
        )
    if route == "upload":
        return RateLimit(
            route,
            settings.upload_rate_limit_requests,
            settings.upload_rate_limit_window_seconds,
        )
    raise ValueError(f"Unsupported rate-limited route: {route}")


async def check_rate_limit(*, request: Request, user_id: str, route: str) -> None:
    """Consume one fixed-window request slot or raise a safe API error.

    Redis is intentionally mandatory in production for these cost-bearing routes.
    Tests may disable it through ``RATE_LIMIT_ENABLED=false``.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled or settings.environment == "test":
        return

    limit = _limit_for(route)
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RATE_LIMIT_DEPENDENCY_UNAVAILABLE",
                "message": "Request protection is temporarily unavailable",
            },
        )

    key = f"rate-limit:{route}:{user_id}"
    try:
        with DependencySpan("redis", "rate_limit"):
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, limit.window_seconds)
            ttl = await redis_client.ttl(key)
    except (RedisError, OSError, AttributeError) as exc:
        lifecycle_event(
            logger,
            "rate_limit_dependency_unavailable",
            level=logging.WARNING,
            request_id=getattr(request.state, "request_id", "unknown"),
            route=route,
            failure_class="unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RATE_LIMIT_DEPENDENCY_UNAVAILABLE",
                "message": "Request protection is temporarily unavailable",
            },
        ) from exc

    retry_after = max(int(ttl), 1)
    if current > limit.maximum:
        lifecycle_event(
            logger,
            "rate_limit_exceeded",
            level=logging.WARNING,
            request_id=getattr(request.state, "request_id", "unknown"),
            route=route,
            limit=limit.maximum,
            window_seconds=limit.window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "Too many requests; try again later",
            },
            headers={"Retry-After": str(retry_after)},
        )


def require_rate_limit(route: str):
    async def _require_rate_limit(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> None:
        await check_rate_limit(
            request=request, user_id=str(current_user.id), route=route
        )

    return _require_rate_limit
