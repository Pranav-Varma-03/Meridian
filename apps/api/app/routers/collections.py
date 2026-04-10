import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.models.entities import User
from app.schemas import (
    BAD_REQUEST_RESPONSE,
    CONFLICT_RESPONSE,
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.services import collections as collection_service

router = APIRouter()


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Product Docs",
                "description": "Documentation for the product team",
            }
        }
    )


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Product Docs (Updated)",
                "description": "Updated description",
            }
        }
    )


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str | None
    document_count: int
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "7ecff269-f648-4601-8d97-1c6f0fabf906",
                "name": "Product Docs",
                "description": "Documentation for the product team",
                "document_count": 12,
                "created_at": "2026-04-08T09:30:00Z",
            }
        }
    )


class CollectionListResponse(BaseModel):
    collections: list[CollectionResponse]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "collections": [],
                "total": 0,
            }
        }
    )


class MessageResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"message": "Collection deleted"}}
    )


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=201,
    summary="Create collection",
    description="Creates a document collection for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        409: CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def create_collection(
    data: CollectionCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new document collection."""
    try:
        result = await collection_service.create_collection(
            session,
            user_id=current_user.id,
            name=data.name,
            description=data.description,
        )
    except collection_service.CollectionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return CollectionResponse(
        id=str(result.collection.id),
        name=result.collection.name,
        description=result.collection.description,
        document_count=result.document_count,
        created_at=result.collection.created_at,
    )


@router.get(
    "",
    response_model=CollectionListResponse,
    status_code=200,
    summary="List collections",
    description="Returns paginated collections for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def list_collections(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List all collections for the authenticated user."""
    collections, total = await collection_service.list_collections(
        session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return CollectionListResponse(
        collections=[
            CollectionResponse(
                id=str(item.collection.id),
                name=item.collection.name,
                description=item.collection.description,
                document_count=item.document_count,
                created_at=item.collection.created_at,
            )
            for item in collections
        ],
        total=total,
    )


@router.get(
    "/{collection_id}",
    response_model=CollectionResponse,
    status_code=200,
    summary="Get collection",
    description="Returns a collection by id for the authenticated user.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def get_collection(
    collection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get collection details."""
    try:
        result = await collection_service.get_collection(
            session,
            user_id=current_user.id,
            collection_id=collection_id,
        )
    except collection_service.CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CollectionResponse(
        id=str(result.collection.id),
        name=result.collection.name,
        description=result.collection.description,
        document_count=result.document_count,
        created_at=result.collection.created_at,
    )


@router.patch(
    "/{collection_id}",
    response_model=CollectionResponse,
    status_code=200,
    summary="Update collection",
    description="Updates collection name or description.",
    responses={
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
        409: CONFLICT_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def update_collection(
    collection_id: uuid.UUID,
    data: CollectionUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Update collection name/description."""
    if data.name is None and data.description is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field (name or description) must be provided",
        )

    try:
        result = await collection_service.update_collection(
            session,
            user_id=current_user.id,
            collection_id=collection_id,
            name=data.name,
            description=data.description,
        )
    except collection_service.CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except collection_service.CollectionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return CollectionResponse(
        id=str(result.collection.id),
        name=result.collection.name,
        description=result.collection.description,
        document_count=result.document_count,
        created_at=result.collection.created_at,
    )


@router.delete(
    "/{collection_id}",
    response_model=MessageResponse,
    status_code=200,
    summary="Delete collection",
    description="Deletes a collection and handles document reassignment or deletion.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def delete_collection(
    collection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a collection and optionally its documents.
    Documents can be moved to default collection or deleted.
    """
    try:
        await collection_service.delete_collection(
            session,
            user_id=current_user.id,
            collection_id=collection_id,
        )
    except collection_service.CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return MessageResponse(message="Collection deleted")
