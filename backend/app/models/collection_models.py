from pydantic import BaseModel
from typing import Any, Optional


class CollectionStorageLocationRequest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None


class CollectionEntryRequest(BaseModel):
    carId: Optional[str] = None
    userId: Optional[str] = None
    itemId: Optional[str] = None
    condition: Optional[str] = None
    purchasePrice: Optional[float] = None
    purchasedAt: Optional[str] = None
    photos: Optional[list[Any]] = None
    createdAt: Optional[str] = None
    attributes: Optional[dict[str, Any]] = None
    count: Optional[int] = None
    updatedAt: Optional[str] = None
    isPublished: Optional[bool] = None
    isInMarket: Optional[bool] = None
    metadata: Optional[bool] = None
    storageLocation: Optional[CollectionStorageLocationRequest] = None
    storageLocationName: Optional[str] = None
    storageLocationId: Optional[str] = None
    notes: Optional[str] = None


class UpsertCollectionRequest(BaseModel):
    items: list[CollectionEntryRequest]


class LikeCollectionRequest(BaseModel):
    carId: str
