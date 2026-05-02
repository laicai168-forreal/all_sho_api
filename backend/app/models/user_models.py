# app/models/user_models.py

from pydantic import BaseModel
from typing import Optional


class UpdateUserRequest(BaseModel):
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


class CreateMessageSocketTicketRequest(BaseModel):
    pass
