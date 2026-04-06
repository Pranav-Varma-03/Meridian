from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_claims
from app.core.database import get_db_session
from app.models.entities import User

router = APIRouter()


class UserProvisionResponse(BaseModel):
    id: str
    auth_subject: str
    email: str | None
    created_at: datetime


@router.post("/me", response_model=UserProvisionResponse)
async def ensure_current_user(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    subject = claims.get("sub")
    email = claims.get("email")

    if not subject:
        raise HTTPException(status_code=401, detail="Token missing subject claim")

    result = await session.execute(select(User).where(User.auth_subject == subject))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(auth_subject=subject, email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif email and user.email != email:
        user.email = email
        await session.commit()
        await session.refresh(user)

    return UserProvisionResponse(
        id=str(user.id),
        auth_subject=user.auth_subject,
        email=user.email,
        created_at=user.created_at,
    )
