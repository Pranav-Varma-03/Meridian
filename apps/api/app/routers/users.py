from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.auth import get_current_user
from app.models.entities import User
from app.schemas import (
    INTERNAL_ERROR_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

router = APIRouter()


class UserProvisionResponse(BaseModel):
    id: str
    auth_subject: str
    email: str | None
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "e3110f0a-7285-4d5e-b36d-9152f954df14",
                "auth_subject": "auth0|65f8f3a5d3f8f7a0d0f5f8a1",
                "email": "user@example.com",
                "created_at": "2026-04-08T09:30:00Z",
            }
        }
    )


@router.post(
    "/me",
    response_model=UserProvisionResponse,
    status_code=200,
    summary="Ensure current authenticated user exists",
    description="Creates or updates the authenticated user record in the local database.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def ensure_current_user(
    user: User = Depends(get_current_user),
):
    return UserProvisionResponse(
        id=str(user.id),
        auth_subject=user.auth_subject,
        email=user.email,
        created_at=user.created_at,
    )
