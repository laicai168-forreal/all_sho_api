from pydantic import BaseModel
from typing import Any, Optional


class CarMutationRequest(BaseModel):
    code: Optional[str] = None
    brand_id: Optional[str] = None
    product_line_id: Optional[str] = None
    make_id: Optional[str] = None
    parent_id: Optional[str] = None
    brand: Optional[str] = None
    make: Optional[str] = None
    product_line: Optional[str] = None
    scale: Optional[str] = None
    image_url: Optional[list[str]] = None
    additional_info: Optional[dict[str, Any]] = None
    title: Optional[str] = None
    images: Optional[list[dict[str, Any]]] = None
    original_id: Optional[str] = None
    release_date_approximate: Optional[str] = None
    description_ai: Optional[str] = None
    make_ai: Optional[str] = None
    model_ai: Optional[str] = None
    source_url: Optional[str] = None
    is_chase: Optional[bool] = None
    is_limited: Optional[bool] = None
    limited_pieces: Optional[int] = None


class CarDuplicateRequest(CarMutationRequest):
    pass


class CarChangeRequestCreate(BaseModel):
    car_id: Optional[str] = None
    request_type: str
    payload: dict[str, Any]
    uploaded_images: Optional[list[dict[str, Any]]] = None


class CarChangeRequestReview(BaseModel):
    status: str
    reviewNotes: Optional[str] = None
    finalPayload: Optional[dict[str, Any]] = None


class CarChangeRequestUpdate(BaseModel):
    request_type: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    uploaded_images: Optional[list[dict[str, Any]]] = None


class CreateCarChangeRequestImageUploadRequest(BaseModel):
    fileName: str
    contentType: str


class CreateAdminCarImageFromUrlRequest(BaseModel):
    imageUrl: str


class HotWheelsStagingReviewRequest(BaseModel):
    reviewStatus: str
    reviewNotes: Optional[str] = None


class HotWheelsStagingBatchReviewRequest(BaseModel):
    itemIds: list[str]
    reviewStatus: str
    reviewNotes: Optional[str] = None
    force: Optional[bool] = False


class HotWheelsImageEnrichmentRequest(BaseModel):
    itemIds: list[str]
    limitPerItem: Optional[int] = 5
    query: Optional[str] = None


class HotWheelsImageCandidateReviewRequest(BaseModel):
    candidateId: str
    action: str


class HotWheelsImageCandidateBatchReviewRequest(BaseModel):
    candidateIds: list[str]
    action: str


class BrandVisibilityUpdateRequest(BaseModel):
    isVisible: bool
