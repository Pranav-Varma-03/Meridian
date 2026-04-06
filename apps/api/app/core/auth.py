import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_jwks_cache: dict[str, Any] = {"keys": None, "expires_at": 0.0}
_jwks_lock = asyncio.Lock()


async def _get_jwks() -> dict[str, Any]:
    now = time.time()
    if _jwks_cache["keys"] is not None and now < _jwks_cache["expires_at"]:
        return _jwks_cache["keys"]

    async with _jwks_lock:
        now = time.time()
        if _jwks_cache["keys"] is not None and now < _jwks_cache["expires_at"]:
            return _jwks_cache["keys"]

        jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks = response.json()

        _jwks_cache["keys"] = jwks
        _jwks_cache["expires_at"] = time.time() + 300
        return jwks


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    return auth_header.split(" ", 1)[1].strip()


async def verify_auth0_access_token(token: str) -> dict[str, Any]:
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token header") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing key id")

    jwks = await _get_jwks()
    public_key = next(
        (key for key in jwks.get("keys", []) if key.get("kid") == kid), None
    )
    if public_key is None:
        raise HTTPException(status_code=401, detail="No matching JWKS key found")

    issuer = f"https://{settings.auth0_domain}/"
    candidate_audiences: list[str] = []

    if settings.auth0_audience:
        candidate_audiences.append(settings.auth0_audience)
    candidate_audiences.append(settings.auth0_client_id)

    last_error: JWTError | None = None
    claims: dict[str, Any] | None = None

    for audience in candidate_audiences:
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
            )
            break
        except JWTError as exc:
            last_error = exc

    if claims is None:
        logger.warning(
            "auth0_token_decode_failed: %s",
            str(last_error) if last_error else "unknown",
        )
        raise HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from last_error

    return claims


async def get_current_user_claims(request: Request) -> dict[str, Any]:
    token = _extract_bearer_token(request)
    return await verify_auth0_access_token(token)
