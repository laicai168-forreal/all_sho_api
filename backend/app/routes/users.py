# app/routes/users.py

from fastapi import APIRouter, Request, HTTPException
from uuid import UUID
from app.common.auth import get_current_user_sub, get_claims
from app.services import profile_image_service, user_service
from app.models.user_models import CreateProfileImageUploadRequest, PromoteUserRequest, UpdateUserRequest

router = APIRouter()
public_router = APIRouter()


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


@router.post("/admin/promote")
def promote_user(request: Request, body: PromoteUserRequest):
    sub = get_current_user_sub(request)

    try:
        return user_service.promote_user(sub, body.cognitoSub, body.role)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/admin/list")
def list_users(
    request: Request,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    sub = get_current_user_sub(request)

    try:
        return user_service.list_users(sub, keyword=keyword, limit=limit, offset=offset)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))


@router.delete("/admin/{user_id}")
def delete_user(request: Request, user_id: UUID):
    sub = get_current_user_sub(request)

    try:
        # UUID typing prevents static admin paths from being accidentally
        # swallowed by this dynamic segment in future route additions.
        return user_service.delete_user(sub, str(user_id))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@public_router.get("/profiles/{user_id}")
def get_public_profile(
    user_id: UUID,
    limit: int = 12,
    offset: int = 0,
):
    # Public collector page stays separate from `/users/...` so visitors can
    # browse profiles without hitting the authenticated user router.
    profile = user_service.get_public_profile(str(user_id), limit=limit, offset=offset)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@public_router.get("/profiles/{user_id}/followers")
def get_public_followers(
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
):
    result = user_service.get_public_followers(str(user_id), limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@public_router.get("/profiles/{user_id}/following")
def get_public_following(
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
):
    result = user_service.get_public_following(str(user_id), limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.get("/follows/{user_id}")
def get_follow_status(request: Request, user_id: UUID):
    sub = get_current_user_sub(request)

    try:
        return user_service.get_follow_status(sub, str(user_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/follows/{user_id}")
def follow_user(request: Request, user_id: UUID):
    sub = get_current_user_sub(request)

    try:
        return user_service.follow_user(sub, str(user_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/follows/{user_id}")
def unfollow_user(request: Request, user_id: UUID):
    sub = get_current_user_sub(request)

    try:
        return user_service.unfollow_user(sub, str(user_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/followers/{user_id}")
def remove_follower(request: Request, user_id: UUID):
    sub = get_current_user_sub(request)

    try:
        return user_service.remove_follower(sub, str(user_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
