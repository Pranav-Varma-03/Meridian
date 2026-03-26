from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid

router = APIRouter()


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    document_count: int
    created_at: datetime


class CollectionListResponse(BaseModel):
    collections: list[CollectionResponse]
    total: int


@router.post("", response_model=CollectionResponse)
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


@router.get("", response_model=CollectionListResponse)
async def list_collections():
    """List all collections for the authenticated user."""
    # TODO: Fetch from database
    return CollectionListResponse(collections=[], total=0)


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(collection_id: str):
    """Get collection details."""
    # TODO: Fetch from database
    raise HTTPException(status_code=404, detail="Collection not found")


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(collection_id: str, data: CollectionCreate):
    """Update collection name/description."""
    # TODO: Update in database
    raise HTTPException(status_code=404, detail="Collection not found")


@router.delete("/{collection_id}")
async def delete_collection(collection_id: str):
    """
    Delete a collection and optionally its documents.
    Documents can be moved to default collection or deleted.
    """
    # TODO: Handle document reassignment or deletion
    return {"message": "Collection deleted"}
