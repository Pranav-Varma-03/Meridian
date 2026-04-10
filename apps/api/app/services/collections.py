import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Collection, Document


class CollectionNotFoundError(Exception):
    """Raised when a collection cannot be found for the current user."""


class CollectionConflictError(Exception):
    """Raised when a collection name already exists for the current user."""


@dataclass(slots=True)
class CollectionWithCount:
    collection: Collection
    document_count: int


async def create_collection(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    description: str | None,
) -> CollectionWithCount:
    normalized_name = name.strip()
    duplicate = await session.scalar(
        select(Collection.id).where(
            Collection.user_id == user_id,
            func.lower(Collection.name) == normalized_name.lower(),
        )
    )
    if duplicate is not None:
        raise CollectionConflictError("Collection with this name already exists")

    collection = Collection(
        user_id=user_id,
        name=normalized_name,
        description=description,
    )
    session.add(collection)
    await session.commit()
    await session.refresh(collection)

    return CollectionWithCount(collection=collection, document_count=0)


async def list_collections(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[CollectionWithCount], int]:
    total = await session.scalar(
        select(func.count(Collection.id)).where(Collection.user_id == user_id)
    )
    total_count = total or 0

    result = await session.execute(
        select(Collection, func.count(Document.id).label("document_count"))
        .outerjoin(Document, Document.collection_id == Collection.id)
        .where(Collection.user_id == user_id)
        .group_by(Collection.id)
        .order_by(Collection.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    collections = [
        CollectionWithCount(collection=row[0], document_count=int(row[1] or 0))
        for row in rows
    ]
    return collections, total_count


async def get_collection(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> CollectionWithCount:
    result = await session.execute(
        select(Collection, func.count(Document.id).label("document_count"))
        .outerjoin(Document, Document.collection_id == Collection.id)
        .where(Collection.user_id == user_id, Collection.id == collection_id)
        .group_by(Collection.id)
    )
    row = result.first()
    if row is None:
        raise CollectionNotFoundError("Collection not found")

    return CollectionWithCount(collection=row[0], document_count=int(row[1] or 0))


async def update_collection(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
    name: str | None,
    description: str | None,
) -> CollectionWithCount:
    collection = await session.scalar(
        select(Collection).where(
            Collection.user_id == user_id,
            Collection.id == collection_id,
        )
    )
    if collection is None:
        raise CollectionNotFoundError("Collection not found")

    if name is not None:
        normalized_name = name.strip()
        duplicate = await session.scalar(
            select(Collection.id).where(
                Collection.user_id == user_id,
                Collection.id != collection_id,
                func.lower(Collection.name) == normalized_name.lower(),
            )
        )
        if duplicate is not None:
            raise CollectionConflictError("Collection with this name already exists")
        collection.name = normalized_name

    if description is not None:
        collection.description = description

    await session.commit()
    await session.refresh(collection)

    document_count = await session.scalar(
        select(func.count(Document.id)).where(Document.collection_id == collection.id)
    )
    return CollectionWithCount(
        collection=collection, document_count=int(document_count or 0)
    )


async def delete_collection(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> None:
    collection = await session.scalar(
        select(Collection).where(
            Collection.user_id == user_id,
            Collection.id == collection_id,
        )
    )
    if collection is None:
        raise CollectionNotFoundError("Collection not found")

    await session.delete(collection)
    await session.commit()
