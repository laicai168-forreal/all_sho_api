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
    user["role"] = user.get("role") or "customer"

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


def promote_user(actor_sub, target_cognito_sub, role):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor or actor.get("role") != "admin":
        raise PermissionError("Admin access required")

    if role not in {"customer", "admin"}:
        raise ValueError("Invalid role")

    updated_rows = user_repository.update_user_role_by_sub(target_cognito_sub, role)
    if not updated_rows:
        return {"message": "user not found"}

    return {"message": "updated", "role": role}


def list_users(actor_sub, keyword=None, limit=50, offset=0):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor or actor.get("role") != "admin":
        raise PermissionError("Admin access required")

    result = user_repository.list_users(keyword=keyword, limit=limit, offset=offset)
    for item in result["items"]:
        item["role"] = item.get("role") or "customer"
    return result


def delete_user(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor or actor.get("role") != "admin":
        raise PermissionError("Admin access required")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        return {"message": "user not found"}

    if actor.get("id") == target_user.get("id"):
        raise ValueError("You cannot delete your own admin account from this page")

    # This admin tool performs a hard delete only when the target user is not
    # referenced by tables with restrictive foreign keys. If the row is blocked
    # by references, we surface a friendly error instead of silently nulling or
    # cascading related data that the schema treats as required.
    result = user_repository.delete_user_by_id(target_user_id)
    if result.get("blocked_by_reference"):
        raise ValueError("User cannot be deleted because related records still reference this account")
    if not result.get("deleted_rows"):
        return {"message": "user not found"}

    return {"message": "deleted"}


def get_public_profile(target_user_id, limit=12, offset=0):
    return user_repository.get_public_profile(target_user_id, limit=limit, offset=offset)


def get_follow_status(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    return user_repository.get_follow_status(actor["id"], target_user_id)


def follow_user(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    if actor["id"] == target_user_id:
        raise ValueError("You cannot follow yourself")

    user_repository.follow_user(actor["id"], target_user_id)
    return user_repository.get_follow_status(actor["id"], target_user_id)


def unfollow_user(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    if actor["id"] == target_user_id:
        raise ValueError("You cannot unfollow yourself")

    user_repository.unfollow_user(actor["id"], target_user_id)
    return user_repository.get_follow_status(actor["id"], target_user_id)


def get_public_followers(target_user_id, limit=20, offset=0):
    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        return None
    return user_repository.list_followers(target_user_id, limit=limit, offset=offset)


def get_public_following(target_user_id, limit=20, offset=0):
    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        return None
    return user_repository.list_following(target_user_id, limit=limit, offset=offset)


def remove_follower(actor_sub, follower_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    follower_user = user_repository.get_user_by_id(follower_user_id)
    if not follower_user:
        raise ValueError("User not found")

    if actor["id"] == follower_user_id:
        raise ValueError("You cannot remove yourself as a follower")

    user_repository.remove_follower(actor["id"], follower_user_id)
    return {"message": "removed"}
