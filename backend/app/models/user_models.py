# app/models/user_models.py

from pydantic import BaseModel
from typing import Optional


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    address: Optional[str] = None
    age: Optional[int] = None
    profileImageUrl: Optional[str] = None
    pendingProfileImageKey: Optional[str] = None
    messageNotificationsMuted: Optional[bool] = None


class PromoteUserRequest(BaseModel):
    cognitoSub: str
    role: str


class CreateProfileImageUploadRequest(BaseModel):
    fileName: str
    contentType: str


class SendDirectMessageRequest(BaseModel):
    text: str


class UpdateTransactionConversationStatusRequest(BaseModel):
    transactionStatus: str


class CreateTransactionReviewRequest(BaseModel):
    rating: int
    comment: str


class CreateMessageSocketTicketRequest(BaseModel):
    pass
