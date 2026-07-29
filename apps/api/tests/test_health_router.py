from types import SimpleNamespace

import pytest

from app.routers import health
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


@pytest.mark.asyncio
async def test_liveness_does_not_require_dependencies() -> None:
    result = await health.liveness_check()

    assert result.status == "healthy"


@pytest.mark.asyncio
async def test_readiness_reports_dependency_failure_without_leaking_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request_with(_FailingRedis(), _FailingSession())
    request.app.state.pinecone = object()
    response = SimpleNamespace(status_code=200)
    monkeypatch.setattr(health, "_generation_status", lambda: "unhealthy")

    result = await health.readiness_check(request, response)

    assert response.status_code == 503
    assert result.status == "unhealthy"
    assert result.redis == "unhealthy"
    assert result.database == "unhealthy"
    assert result.pinecone == "unhealthy"
