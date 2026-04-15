# app/routes/users.py

from fastapi import APIRouter, Request, HTTPException
from app.common.auth import get_current_user_sub, get_claims
from app.services import profile_image_service, user_service
from app.models.user_models import CreateProfileImageUploadRequest, UpdateUserRequest

router = APIRouter()


@router.post("")
def create_user(request: Request):
    claims = get_claims(request)

    sub = claims["sub"]
    email = claims.get("email")
    phone = claims.get("phone_number")

    user_service.create_user_if_not_exists(sub, email, phone, claims)

    return {"message": "user created"}


@router.get("/me")
def get_me(request: Request):
    sub = get_current_user_sub(request)
    claims = get_claims(request)

    user = user_service.get_user_profile(sub, claims)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.post("/me")
def update_me(request: Request, body: UpdateUserRequest):
    sub = get_current_user_sub(request)

    updated_rows = user_service.update_user_profile(sub, body.dict())

    if not updated_rows:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "updated"}


@router.post("/profile-image/upload")
def create_profile_image_upload(request: Request, body: CreateProfileImageUploadRequest):
    sub = get_current_user_sub(request)

    return profile_image_service.create_profile_image_upload(
        sub,
        body.fileName,
        body.contentType,
    )
