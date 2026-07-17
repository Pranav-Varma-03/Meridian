from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.core.auth import get_current_user_claims
from app.core.config import get_settings
from app.schemas import NOT_FOUND_RESPONSE, UNAUTHORIZED_RESPONSE

router = APIRouter()
settings = get_settings()


class TokenClaimsResponse(BaseModel):
    iss: str | None
    aud: str | list[str] | None
    permissions: list[str]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "iss": "https://your-tenant.us.auth0.com/",
                "aud": "https://api.meridian.local",
                "permissions": ["documents:reingest"],
            }
        }
    )


def _permissions_from_claims(claims: dict[str, Any]) -> list[str]:
    permissions = claims.get("permissions")
    if not isinstance(permissions, list):
        return []
    return [permission for permission in permissions if isinstance(permission, str)]


async def require_development_environment() -> None:
    if settings.environment.lower() != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get(
    "/token-claims",
    response_model=TokenClaimsResponse,
    status_code=200,
    summary="Inspect verified access-token claims (development only)",
    description=(
        "Development-only diagnostic endpoint. It returns an allowlisted subset "
        "of claims only after normal Auth0 bearer-token verification. "
        "It returns 404 outside the development environment."
    ),
    responses={401: UNAUTHORIZED_RESPONSE, 404: NOT_FOUND_RESPONSE},
)
async def get_verified_token_claims(
    _development_only: None = Depends(require_development_environment),
    claims: dict[str, Any] = Depends(get_current_user_claims),
) -> TokenClaimsResponse:
    audience = claims.get("aud")
    if isinstance(audience, list):
        audience = [value for value in audience if isinstance(value, str)]
    elif not isinstance(audience, str):
        audience = None

    issuer = claims.get("iss")
    return TokenClaimsResponse(
        iss=issuer if isinstance(issuer, str) else None,
        aud=audience,
        permissions=_permissions_from_claims(claims),
    )
