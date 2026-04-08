from types import SimpleNamespace

import pytest

from app.routers.health import health_check


class _HealthyRedis:
    async def ping(self) -> bool:
        return True


class _FailingRedis:
    async def ping(self) -> bool:
        raise RuntimeError("redis down")


class _HealthySession:
    async def execute(self, _query):
        return 1


class _FailingSession:
    async def execute(self, _query):
        raise RuntimeError("db down")


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _request_with(redis_client, session):
    app_state = SimpleNamespace(
        redis=redis_client,
        db_session_factory=lambda: _SessionContext(session),
    )
    return SimpleNamespace(app=SimpleNamespace(state=app_state))


@pytest.mark.asyncio
async def test_health_check_healthy() -> None:
    request = _request_with(_HealthyRedis(), _HealthySession())

    result = await health_check(request)

    assert result.status == "healthy"
    assert result.redis == "healthy"
    assert result.database == "healthy"


@pytest.mark.asyncio
async def test_health_check_degraded_when_dependencies_fail() -> None:
    request = _request_with(_FailingRedis(), _FailingSession())

    result = await health_check(request)

    assert result.status == "degraded"
    assert result.redis == "unhealthy"
    assert result.database == "unhealthy"
