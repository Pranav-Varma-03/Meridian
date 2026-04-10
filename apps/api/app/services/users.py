from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import User


class InvalidUserClaimsError(Exception):
    """Raised when token claims are missing required user identity data."""


async def ensure_user_from_claims(
    session: AsyncSession,
    claims: dict,
) -> User:
    subject = claims.get("sub")
    email = claims.get("email")

    if not subject:
        raise InvalidUserClaimsError("Token missing subject claim")

    existing_user = await session.scalar(
        select(User).where(User.auth_subject == subject)
    )
    if existing_user is not None:
        if email and existing_user.email != email:
            existing_user.email = email
            await session.commit()
            await session.refresh(existing_user)
        return existing_user

    user = User(auth_subject=subject, email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
