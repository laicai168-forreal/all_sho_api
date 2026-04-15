# app/services/user_service.py

from app.repositories import user_repository
from app.services import profile_image_service


def _get_cognito_username(claims):
    return (
        claims.get("preferred_username")
        or claims.get("cognito:username")
        or claims.get("email")
        or claims.get("phone_number")
        or "user"
    )


def create_user_if_not_exists(sub, email, phone, claims):
    username = _get_cognito_username(claims)
    user_repository.create_user(sub, email, phone, username)


def get_user_profile(sub, claims):
    user = user_repository.get_user_by_sub(sub)
    if not user:
        return None

    # merge Cognito data
    user["username"] = _get_cognito_username(claims)
    user["email"] = claims.get("email")
    user["phone_number"] = claims.get("phone_number")

    return user


def update_user_profile(sub, data):
    current_user = user_repository.get_user_by_sub(sub)
    if not current_user:
        return 0

    profile_image_url = current_user.get("profile_image_url")
    pending_profile_image_key = data.get("pendingProfileImageKey")

    if pending_profile_image_key:
        profile_image_url = profile_image_service.confirm_profile_image(
            sub,
            pending_profile_image_key,
            profile_image_url,
        )
    elif data.get("profileImageUrl") is not None:
        profile_image_url = data.get("profileImageUrl")

    return user_repository.update_user(
        sub,
        data.get("bio"),
        data.get("address"),
        data.get("age"),
        profile_image_url,
    )
