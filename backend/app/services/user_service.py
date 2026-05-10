# app/services/user_service.py

from app.repositories import showroom_repository, user_repository
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
    user["message_notifications_muted"] = bool(user.get("message_notifications_muted"))

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
    elif "profileImageUrl" in data:
        profile_image_url = data.get("profileImageUrl")

    bio = data.get("bio") if "bio" in data else current_user.get("bio")
    address = data.get("address") if "address" in data else current_user.get("address")
    age = data.get("age") if "age" in data else current_user.get("age")
    message_notifications_muted = (
        data.get("messageNotificationsMuted")
        if "messageNotificationsMuted" in data
        else current_user.get("message_notifications_muted")
    )

    return user_repository.update_user(
        sub,
        bio,
        address,
        age,
        profile_image_url,
        bool(message_notifications_muted),
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
    profile = user_repository.get_public_profile(target_user_id, limit=limit, offset=offset)
    if not profile:
        return None

    profile["reviews"] = {
        "summary": showroom_repository.get_user_review_summary(target_user_id),
        "items": showroom_repository.list_recent_user_reviews(target_user_id, limit=5),
    }
    return profile


def get_public_reviews(target_user_id, limit=10, offset=0):
    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        return None

    safe_limit = min(max(limit or 10, 1), 20)
    safe_offset = max(offset or 0, 0)
    summary = showroom_repository.get_user_review_summary(target_user_id)
    return {
        "summary": summary,
        "items": showroom_repository.list_recent_user_reviews(target_user_id, limit=safe_limit, offset=safe_offset),
        "total": summary.get("totalReviews", 0),
        "limit": safe_limit,
        "offset": safe_offset,
    }


def get_follow_status(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    return user_repository.get_follow_status(actor["id"], target_user_id)


def _get_relationship_status_or_raise(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    return actor, target_user, user_repository.get_follow_status(actor["id"], target_user_id)


def follow_user(actor_sub, target_user_id):
    actor, _, relationship = _get_relationship_status_or_raise(actor_sub, target_user_id)

    if actor["id"] == target_user_id:
        raise ValueError("You cannot follow yourself")

    if relationship["blocking"]:
        raise ValueError("You have blocked this user. Unblock them before following again.")

    if relationship["blockedBy"]:
        raise ValueError("You cannot follow a user who has blocked you.")

    user_repository.follow_user(actor["id"], target_user_id)
    return user_repository.get_follow_status(actor["id"], target_user_id)


def unfollow_user(actor_sub, target_user_id):
    actor, _, _ = _get_relationship_status_or_raise(actor_sub, target_user_id)

    if actor["id"] == target_user_id:
        raise ValueError("You cannot unfollow yourself")

    user_repository.unfollow_user(actor["id"], target_user_id)
    return user_repository.get_follow_status(actor["id"], target_user_id)


def block_user(actor_sub, target_user_id):
    actor, _, _ = _get_relationship_status_or_raise(actor_sub, target_user_id)

    if actor["id"] == target_user_id:
        raise ValueError("You cannot block yourself")

    user_repository.block_user(actor["id"], target_user_id)
    return user_repository.get_follow_status(actor["id"], target_user_id)


def unblock_user(actor_sub, target_user_id):
    actor, _, _ = _get_relationship_status_or_raise(actor_sub, target_user_id)

    if actor["id"] == target_user_id:
        raise ValueError("You cannot unblock yourself")

    user_repository.unblock_user(actor["id"], target_user_id)
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
