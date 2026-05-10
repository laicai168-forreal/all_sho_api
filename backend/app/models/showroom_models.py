from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateShowroomImageUploadRequest(BaseModel):
    fileName: str
    contentType: str


class CreateShowroomPendingImageRequest(BaseModel):
    objectKey: str
    fileName: str
    sortOrder: int = 0


class CreateShowroomSellingDetailsRequest(BaseModel):
    price: Decimal = Field(..., gt=0)
    currency: str = "USD"
    condition: Optional[str] = None
    location: Optional[str] = None
    shippingSupported: bool = False


class CreateShowroomPostRequest(BaseModel):
    postType: Literal["display_only", "selling"] = "display_only"
    title: str
    description: str = ""
    visibility: Literal["public"] = "public"
    tags: list[str] = Field(default_factory=list)
    carIds: list[str] = Field(default_factory=list)
    images: list[CreateShowroomPendingImageRequest] = Field(default_factory=list)
    sellingDetails: Optional[CreateShowroomSellingDetailsRequest] = None


class UpdateShowroomPostRequest(BaseModel):
    postType: Literal["display_only", "selling"] = "display_only"
    title: str
    description: str = ""
    visibility: Literal["public"] = "public"
    tags: list[str] = Field(default_factory=list)
    carIds: list[str] = Field(default_factory=list)
    images: list[CreateShowroomPendingImageRequest] = Field(default_factory=list)
    sellingDetails: Optional[CreateShowroomSellingDetailsRequest] = None


class UpdateShowroomSellingStatusRequest(BaseModel):
    sellingStatus: Literal["available", "pending", "sold"]


class ConfirmShowroomSaleBuyerRequest(BaseModel):
    buyerUserId: str


class CreateShowroomCommentRequest(BaseModel):
    content: str


class CreateShowroomReportRequest(BaseModel):
    reason: str
    details: Optional[str] = None


class ModerateShowroomPostRequest(BaseModel):
    status: Literal["published", "hidden", "deleted"]


class ModerateShowroomCommentRequest(BaseModel):
    status: Literal["published", "deleted"]


class ResolveShowroomReportRequest(BaseModel):
    status: Literal["reviewed", "dismissed"]
    reviewNotes: Optional[str] = None
