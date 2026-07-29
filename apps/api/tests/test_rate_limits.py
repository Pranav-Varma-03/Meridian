from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import rate_limits


class _RedisCounter:
    def __init__(self, count: int) -> None:
        self.count = count
        self.expiries: list[tuple[str, int]] = []

    async def incr(self, _key: str) -> int:
        return self.count

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries.append((key, seconds))

    async def ttl(self, _key: str) -> int:
        return 42


class _UnavailableRedis:
    async def incr(self, _key: str) -> int:
        raise OSError("connection unavailable")


def _settings():
    return SimpleNamespace(
        rate_limit_enabled=True,
        environment="production",
        chat_rate_limit_requests=20,
        chat_rate_limit_window_seconds=60,
        upload_rate_limit_requests=10,
        upload_rate_limit_window_seconds=3600,
    )


def _request(redis_client):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=redis_client)),
        state=SimpleNamespace(request_id="request-1"),
    )


@pytest.mark.asyncio
async def test_rate_limit_allows_request_within_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rate_limits, "get_settings", _settings)
    redis_client = _RedisCounter(count=1)

    await rate_limits.check_rate_limit(
        request=_request(redis_client), user_id="user-1", route="chat"
    )

    assert redis_client.expiries == [("rate-limit:chat:user-1", 60)]


@pytest.mark.asyncio
async def test_rate_limit_returns_retry_after_when_exceeded(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(rate_limits, "get_settings", _settings)

    with pytest.raises(HTTPException) as exc_info:
        await rate_limits.check_rate_limit(
            request=_request(_RedisCounter(count=21)), user_id="user-1", route="chat"
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "RATE_LIMITED"
    assert exc_info.value.headers == {"Retry-After": "42"}


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(rate_limits, "get_settings", _settings)

    with pytest.raises(HTTPException) as exc_info:
        await rate_limits.check_rate_limit(
            request=_request(_UnavailableRedis()), user_id="user-1", route="upload"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "RATE_LIMIT_DEPENDENCY_UNAVAILABLE"
