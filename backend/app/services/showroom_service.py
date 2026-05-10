import uuid

from app.repositories import showroom_repository, user_repository
from app.services import message_service
from app.services import profile_image_service


MAX_SHOWROOM_IMAGES = 10
MAX_SHOWROOM_CARS = 10
MAX_SHOWROOM_TAGS = 12
MAX_TITLE_LENGTH = 140
MAX_DESCRIPTION_LENGTH = 5000
MAX_COMMENT_LENGTH = 1200
MAX_REPORT_REASON_LENGTH = 120
MAX_REPORT_DETAILS_LENGTH = 1000
PUBLIC_FEED_MODES = {"recent", "hot_topics", "popular"}
AUTH_FEED_MODES = PUBLIC_FEED_MODES | {"following", "friends"}


def _normalize_tags(tags):
    normalized = []
    seen = set()

    for raw_tag in tags or []:
        cleaned = str(raw_tag or "").strip().lstrip("#")
        if not cleaned:
            continue

        tag_key = "".join(char for char in cleaned.lower() if char.isalnum() or char in ("-", "_"))
        if not tag_key or tag_key in seen:
            continue

        seen.add(tag_key)
        normalized.append({
            "tag_key": tag_key[:40],
            "display_name": f"#{cleaned[:40]}",
        })

    return normalized[:MAX_SHOWROOM_TAGS]


def _normalize_tag_key(tag_key):
    cleaned = str(tag_key or "").strip().lstrip("#")
    normalized = "".join(char for char in cleaned.lower() if char.isalnum() or char in ("-", "_"))
    return normalized[:40]


def _ensure_actor(actor_sub):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("User not found")
    return actor


def _ensure_not_blocked(actor_id, target_user_id):
    relationship = user_repository.get_follow_status(actor_id, target_user_id)
    if relationship.get("blocking"):
        raise ValueError("You have blocked this collector.")
    if relationship.get("blockedBy"):
        raise ValueError("This collector has blocked you.")
    return relationship


def _ensure_admin(actor_sub):
    actor = _ensure_actor(actor_sub)
    if actor.get("role") != "admin":
        raise ValueError("Admin access required")
    return actor


def _enforce_showroom_post_rate_limit(user_id):
    recent_count = showroom_repository.count_recent_showroom_posts(user_id, window_minutes=60)
    if recent_count >= 6:
        raise ValueError("Too many showroom posts in a short time. Please wait before posting again.")


def _enforce_showroom_comment_rate_limit(user_id):
    recent_count = showroom_repository.count_recent_showroom_comments(user_id, window_minutes=10)
    if recent_count >= 20:
        raise ValueError("Too many comments in a short time. Please slow down and try again shortly.")


def _enforce_showroom_report_rate_limit(user_id):
    recent_count = showroom_repository.count_recent_showroom_reports(user_id, window_minutes=60)
    if recent_count >= 10:
        raise ValueError("Too many reports in a short time. Please wait before submitting another report.")


def create_showroom_image_upload(actor_sub, file_name, content_type):
    _ensure_actor(actor_sub)
    return profile_image_service.create_showroom_image_upload(actor_sub, file_name, content_type)


def create_showroom_post(actor_sub, payload):
    actor = _ensure_actor(actor_sub)
    normalized = _normalize_showroom_post_payload(payload)
    _enforce_showroom_post_rate_limit(actor["id"])

    post_id = str(uuid.uuid4())
    confirmed_images = profile_image_service.confirm_showroom_images(actor_sub, post_id, normalized["images"])

    showroom_repository.create_showroom_post(
        post_id=post_id,
        user_id=actor["id"],
        post_type=normalized["post_type"],
        title=normalized["title"],
        description=normalized["description"],
        visibility=normalized["visibility"],
        tags=normalized["tags"],
        car_ids=normalized["car_ids"],
        images=confirmed_images,
        selling_details=normalized["selling_details"],
    )
    return showroom_repository.get_showroom_post(post_id)


def _normalize_showroom_post_payload(payload):
    post_type = payload.get("postType") or "display_only"
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    visibility = payload.get("visibility") or "public"
    images = payload.get("images") or []
    car_ids = list(dict.fromkeys(payload.get("carIds") or []))
    tags = _normalize_tags(payload.get("tags") or [])
    selling_details = payload.get("sellingDetails")

    if not title:
        raise ValueError("Title is required")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title is too long. Keep it under {MAX_TITLE_LENGTH} characters.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Description is too long. Keep it under {MAX_DESCRIPTION_LENGTH} characters.")
    if len(images) > MAX_SHOWROOM_IMAGES:
        raise ValueError(f"You can upload at most {MAX_SHOWROOM_IMAGES} images.")
    if len(car_ids) > MAX_SHOWROOM_CARS:
        raise ValueError(f"You can link at most {MAX_SHOWROOM_CARS} cars.")
    if post_type not in {"display_only", "selling"}:
        raise ValueError("Invalid post type")
    if visibility != "public":
        raise ValueError("Only public showroom posts are supported right now")
    if post_type == "selling" and not selling_details:
        raise ValueError("Selling posts require price information")
    if post_type == "display_only":
        selling_details = None

    return {
        "post_type": post_type,
        "title": title,
        "description": description,
        "visibility": visibility,
        "images": images,
        "car_ids": car_ids,
        "tags": tags,
        "selling_details": selling_details,
    }


def update_showroom_post(actor_sub, post_id, payload):
    actor = _ensure_actor(actor_sub)
    normalized = _normalize_showroom_post_payload(payload)
    existing = showroom_repository.get_showroom_post(post_id)
    if not existing:
        raise ValueError("Post not found")
    if existing["author"]["id"] != actor["id"]:
        raise ValueError("You can only edit your own showroom posts")

    resolved_images = profile_image_service.resolve_showroom_images(actor_sub, post_id, normalized["images"])
    result = showroom_repository.update_showroom_post(
        post_id=post_id,
        user_id=actor["id"],
        post_type=normalized["post_type"],
        title=normalized["title"],
        description=normalized["description"],
        visibility=normalized["visibility"],
        tags=normalized["tags"],
        car_ids=normalized["car_ids"],
        images=resolved_images,
        selling_details=normalized["selling_details"],
    )
    if not result.get("updated"):
        raise ValueError("Post not found")
    return showroom_repository.get_showroom_post(post_id)


def update_showroom_selling_status(actor_sub, post_id, selling_status):
    actor = _ensure_actor(actor_sub)
    normalized_status = str(selling_status or "").strip().lower()
    if normalized_status not in {"available", "pending", "sold"}:
        raise ValueError("Invalid selling status")

    existing = showroom_repository.get_showroom_post(post_id)
    if not existing:
        raise ValueError("Post not found")
    if existing["author"]["id"] != actor["id"]:
        raise ValueError("You can only update your own selling posts")
    if existing["post_type"] != "selling" or not existing.get("selling_details"):
        raise ValueError("Only selling posts can update selling status")

    result = showroom_repository.update_showroom_selling_status(
        post_id=post_id,
        user_id=actor["id"],
        selling_status=normalized_status,
    )
    if not result.get("updated"):
        raise ValueError("Post not found")
    if normalized_status != "sold":
        showroom_repository.delete_showroom_sale_transaction(post_id, actor["id"])
    return showroom_repository.get_showroom_post(post_id)


def list_showroom_sale_candidates(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)
    post = showroom_repository.get_showroom_post(post_id)
    if not post:
        raise ValueError("Post not found")
    if post["author"]["id"] != actor["id"]:
        raise ValueError("You can only manage your own selling posts")
    if post["post_type"] != "selling" or not post.get("selling_details"):
        raise ValueError("Only selling posts support buyer confirmation")

    candidates = [
        candidate
        for candidate in message_service.list_direct_conversation_partners(actor_sub)
        if not candidate.get("blocking") and not candidate.get("blockedBy")
    ]
    return {
        "items": candidates,
        "transaction": showroom_repository.get_showroom_sale_transaction(post_id),
    }


def confirm_showroom_sale_buyer(actor_sub, post_id, buyer_user_id):
    actor = _ensure_actor(actor_sub)
    post = showroom_repository.get_showroom_post(post_id)
    if not post:
        raise ValueError("Post not found")
    if post["author"]["id"] != actor["id"]:
        raise ValueError("You can only manage your own selling posts")
    if post["post_type"] != "selling" or not post.get("selling_details"):
        raise ValueError("Only selling posts support buyer confirmation")

    current_status = post["selling_details"].get("sellingStatus") or post["selling_details"].get("selling_status") or "available"
    if current_status != "sold":
        raise ValueError("Mark the post as sold before confirming the buyer")

    normalized_buyer_user_id = str(buyer_user_id or "").strip()
    if not normalized_buyer_user_id:
        raise ValueError("Buyer is required")
    if normalized_buyer_user_id == actor["id"]:
        raise ValueError("Seller and buyer cannot be the same user")

    buyer = user_repository.get_user_by_id(normalized_buyer_user_id)
    if not buyer:
        raise ValueError("Buyer not found")

    candidates = message_service.list_direct_conversation_partners(actor_sub)
    candidate_ids = {
        str(candidate.get("userId"))
        for candidate in candidates
        if candidate.get("userId") and not candidate.get("blocking") and not candidate.get("blockedBy")
    }
    if normalized_buyer_user_id not in candidate_ids:
        raise ValueError("Buyer must come from your existing message conversations")

    transaction = showroom_repository.upsert_showroom_sale_transaction(
        post_id=post_id,
        seller_user_id=actor["id"],
        buyer_user_id=normalized_buyer_user_id,
    )
    return {
        "transaction": transaction,
    }


def _normalize_marketplace_filters(keyword=None, seller_query=None, min_price=None, max_price=None, shipping_supported=None, selling_status=None):
    normalized_keyword = str(keyword or "").strip() or None
    normalized_seller_query = str(seller_query or "").strip() or None
    normalized_selling_status = str(selling_status or "").strip().lower() or None

    if min_price is not None and min_price < 0:
        raise ValueError("Minimum price cannot be negative")
    if max_price is not None and max_price < 0:
        raise ValueError("Maximum price cannot be negative")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("Minimum price cannot be greater than maximum price")
    if normalized_selling_status and normalized_selling_status not in {"available", "pending", "sold"}:
        raise ValueError("Invalid selling status")

    return {
        "keyword": normalized_keyword,
        "seller_query": normalized_seller_query,
        "min_price": min_price,
        "max_price": max_price,
        "shipping_supported": shipping_supported,
        "selling_status": normalized_selling_status,
    }


def list_showroom_posts(limit=20, offset=0, user_id=None, post_type=None, feed_mode=None, tag_key=None, car_id=None, keyword=None, seller_query=None, min_price=None, max_price=None, shipping_supported=None, selling_status=None):
    normalized_feed_mode = (feed_mode or "recent").strip().lower()
    normalized_tag_key = _normalize_tag_key(tag_key) if tag_key else None
    filters = _normalize_marketplace_filters(
        keyword=keyword,
        seller_query=seller_query,
        min_price=min_price,
        max_price=max_price,
        shipping_supported=shipping_supported,
        selling_status=selling_status,
    )
    if post_type and post_type not in {"display_only", "selling"}:
        raise ValueError("Invalid post type")
    if normalized_feed_mode not in PUBLIC_FEED_MODES:
        raise ValueError("Invalid public feed mode")
    if tag_key and not normalized_tag_key:
        raise ValueError("Invalid tag")
    return showroom_repository.list_showroom_posts(
        limit=limit,
        offset=offset,
        user_id=user_id,
        post_type=post_type,
        feed_mode=normalized_feed_mode,
        tag_key=normalized_tag_key,
        car_id=car_id,
        **filters,
    )


def list_showroom_feed(actor_sub, feed_mode, limit=20, offset=0, post_type=None, tag_key=None, car_id=None, keyword=None, seller_query=None, min_price=None, max_price=None, shipping_supported=None, selling_status=None):
    actor = _ensure_actor(actor_sub)

    normalized_feed_mode = (feed_mode or "recent").strip().lower()
    normalized_tag_key = _normalize_tag_key(tag_key) if tag_key else None
    filters = _normalize_marketplace_filters(
        keyword=keyword,
        seller_query=seller_query,
        min_price=min_price,
        max_price=max_price,
        shipping_supported=shipping_supported,
        selling_status=selling_status,
    )
    if normalized_feed_mode not in AUTH_FEED_MODES:
        raise ValueError("Invalid feed mode")
    if post_type and post_type not in {"display_only", "selling"}:
        raise ValueError("Invalid post type")
    if tag_key and not normalized_tag_key:
        raise ValueError("Invalid tag")

    return showroom_repository.list_showroom_posts(
        limit=limit,
        offset=offset,
        post_type=post_type,
        feed_mode=normalized_feed_mode,
        actor_id=actor["id"],
        tag_key=normalized_tag_key,
        car_id=car_id,
        **filters,
    )


def list_trending_showroom_tags(limit=12):
    safe_limit = min(max(limit or 12, 1), 30)
    return {
        "items": showroom_repository.list_trending_showroom_tags(limit=safe_limit),
        "limit": safe_limit,
    }


def get_showroom_post(post_id):
    return showroom_repository.get_showroom_post(post_id)


def get_showroom_post_for_actor(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)
    return showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])


def get_showroom_post_like_status(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)

    post = showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])
    if not post:
        raise ValueError("Post not found")

    _ensure_not_blocked(actor["id"], post["author"]["id"])

    return {
        "viewerHasLiked": showroom_repository.get_showroom_post_like_status(post_id, actor["id"]),
    }


def list_showroom_comments(post_id, limit=30, offset=0, actor_sub=None):
    actor_id = None
    if actor_sub:
        actor_id = _ensure_actor(actor_sub)["id"]
    post = showroom_repository.get_showroom_post(post_id, actor_id=actor_id)
    if not post:
        raise ValueError("Post not found")
    return showroom_repository.list_showroom_comments(post_id, limit=limit, offset=offset, actor_id=actor_id)


def create_showroom_comment(actor_sub, post_id, content):
    actor = _ensure_actor(actor_sub)

    post = showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])
    if not post:
        raise ValueError("Post not found")
    _ensure_not_blocked(actor["id"], post["author"]["id"])

    normalized_content = (content or "").strip()
    if not normalized_content:
        raise ValueError("Comment text is required")
    if len(normalized_content) > MAX_COMMENT_LENGTH:
        raise ValueError(f"Comment is too long. Keep it under {MAX_COMMENT_LENGTH} characters.")
    _enforce_showroom_comment_rate_limit(actor["id"])

    return showroom_repository.create_showroom_comment(
        post_id=post_id,
        user_id=actor["id"],
        content=normalized_content,
    )


def delete_showroom_comment(actor_sub, comment_id):
    actor = _ensure_actor(actor_sub)

    result = showroom_repository.delete_showroom_comment(
        comment_id=comment_id,
        user_id=actor["id"],
    )
    if not result["deleted"]:
        raise ValueError("Comment not found")
    return {"message": "deleted"}


def like_showroom_post(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)

    post = showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])
    if not post:
        raise ValueError("Post not found")
    _ensure_not_blocked(actor["id"], post["author"]["id"])

    showroom_repository.like_showroom_post(post_id=post_id, user_id=actor["id"])
    return {
        "viewerHasLiked": True,
        "post": showroom_repository.get_showroom_post(post_id),
    }


def unlike_showroom_post(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)

    post = showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])
    if not post:
        raise ValueError("Post not found")
    _ensure_not_blocked(actor["id"], post["author"]["id"])

    showroom_repository.unlike_showroom_post(post_id=post_id, user_id=actor["id"])
    return {
        "viewerHasLiked": False,
        "post": showroom_repository.get_showroom_post(post_id),
    }


def delete_showroom_post(actor_sub, post_id):
    actor = _ensure_actor(actor_sub)

    result = showroom_repository.delete_showroom_post(post_id=post_id, user_id=actor["id"])
    if not result["deleted"]:
        raise ValueError("Post not found")
    return {"message": "deleted"}


def create_showroom_post_report(actor_sub, post_id, reason, details=None):
    actor = _ensure_actor(actor_sub)
    post = showroom_repository.get_showroom_post(post_id, actor_id=actor["id"])
    if not post:
        raise ValueError("Post not found")
    if post["author"]["id"] == actor["id"]:
        raise ValueError("You cannot report your own post")
    _ensure_not_blocked(actor["id"], post["author"]["id"])

    normalized_reason = (reason or "").strip()
    normalized_details = (details or "").strip() or None
    if not normalized_reason:
        raise ValueError("Report reason is required")
    if len(normalized_reason) > MAX_REPORT_REASON_LENGTH:
        raise ValueError(f"Report reason is too long. Keep it under {MAX_REPORT_REASON_LENGTH} characters.")
    if normalized_details and len(normalized_details) > MAX_REPORT_DETAILS_LENGTH:
        raise ValueError(f"Report details are too long. Keep them under {MAX_REPORT_DETAILS_LENGTH} characters.")
    _enforce_showroom_report_rate_limit(actor["id"])

    return showroom_repository.create_showroom_report(
        reporter_id=actor["id"],
        post_id=post_id,
        reason=normalized_reason,
        details=normalized_details,
    )


def create_showroom_comment_report(actor_sub, comment_id, reason, details=None):
    actor = _ensure_actor(actor_sub)
    comment = showroom_repository.get_showroom_comment(comment_id)
    if not comment or comment.get("status") != "published":
        raise ValueError("Comment not found")
    if comment["author"]["id"] == actor["id"]:
        raise ValueError("You cannot report your own comment")
    _ensure_not_blocked(actor["id"], comment["author"]["id"])

    normalized_reason = (reason or "").strip()
    normalized_details = (details or "").strip() or None
    if not normalized_reason:
        raise ValueError("Report reason is required")
    if len(normalized_reason) > MAX_REPORT_REASON_LENGTH:
        raise ValueError(f"Report reason is too long. Keep it under {MAX_REPORT_REASON_LENGTH} characters.")
    if normalized_details and len(normalized_details) > MAX_REPORT_DETAILS_LENGTH:
        raise ValueError(f"Report details are too long. Keep them under {MAX_REPORT_DETAILS_LENGTH} characters.")
    _enforce_showroom_report_rate_limit(actor["id"])

    return showroom_repository.create_showroom_report(
        reporter_id=actor["id"],
        comment_id=comment_id,
        reason=normalized_reason,
        details=normalized_details,
    )


def list_admin_showroom_reports(actor_sub, limit=50, offset=0, status=None):
    _ensure_admin(actor_sub)
    normalized_status = (status or "").strip().lower() or None
    if normalized_status and normalized_status not in {"open", "reviewed", "dismissed"}:
        raise ValueError("Invalid report status")
    return showroom_repository.list_showroom_reports(limit=limit, offset=offset, status=normalized_status)


def moderate_showroom_post(actor_sub, post_id, status):
    _ensure_admin(actor_sub)
    if status not in {"published", "hidden", "deleted"}:
        raise ValueError("Invalid post status")
    result = showroom_repository.update_showroom_post_status(post_id, status)
    if not result["updated"]:
        raise ValueError("Post not found")
    return {"message": "updated", "status": status}


def moderate_showroom_comment(actor_sub, comment_id, status):
    _ensure_admin(actor_sub)
    if status not in {"published", "deleted"}:
        raise ValueError("Invalid comment status")
    result = showroom_repository.update_showroom_comment_status(comment_id, status)
    if not result["updated"]:
        raise ValueError("Comment not found")
    return {"message": "updated", "status": status}


def resolve_showroom_report(actor_sub, report_id, status, review_notes=None):
    actor = _ensure_admin(actor_sub)
    if status not in {"reviewed", "dismissed"}:
        raise ValueError("Invalid report status")
    normalized_review_notes = (review_notes or "").strip() or None
    result = showroom_repository.resolve_showroom_report(
        report_id=report_id,
        reviewer_id=actor["id"],
        status=status,
        review_notes=normalized_review_notes,
    )
    if not result["updated"]:
        raise ValueError("Report not found")
    return {"message": "updated", "status": status}
