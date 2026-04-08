import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.schemas import (
    CONFLICT_RESPONSE,
    INTERNAL_ERROR_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)

router = APIRouter()


class CollectionCreate(BaseModel):
    name: str
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
    name: str | None = None
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
async def create_collection(data: CollectionCreate):
    """Create a new document collection."""
    # TODO: Create in database
    return CollectionResponse(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        document_count=0,
        created_at=datetime.utcnow(),
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
async def list_collections():
    """List all collections for the authenticated user."""
    # TODO: Fetch from database
    return CollectionListResponse(collections=[], total=0)


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
async def get_collection(collection_id: str):
    """Get collection details."""
    # TODO: Fetch from database
    raise HTTPException(status_code=404, detail="Collection not found")


@router.patch(
    "/{collection_id}",
    response_model=CollectionResponse,
    status_code=200,
    summary="Update collection",
    description="Updates collection name or description.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
        500: INTERNAL_ERROR_RESPONSE,
    },
)
async def update_collection(collection_id: str, data: CollectionUpdate):
    """Update collection name/description."""
    # TODO: Update in database
    raise HTTPException(status_code=404, detail="Collection not found")


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
async def delete_collection(collection_id: str):
    """
    Delete a collection and optionally its documents.
    Documents can be moved to default collection or deleted.
    """
    # TODO: Handle document reassignment or deletion
    return {"message": "Collection deleted"}
