import json
import os
import time
import uuid
from decimal import Decimal
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.repositories import showroom_repository, user_repository


MESSAGING_TABLE_NAME = os.environ.get("USER_MESSAGING_TABLE", "")
MESSAGING_WS_URL = os.environ.get("MESSAGING_WS_URL", "")
MESSAGING_WS_CALLBACK_URL = os.environ.get("MESSAGING_WS_CALLBACK_URL", "")
DEFAULT_THREAD_PAGE_SIZE = 30
MAX_THREAD_PAGE_SIZE = 50
MAX_MESSAGE_LENGTH = 500
MAX_MESSAGES_PER_MINUTE = 20
MAX_MESSAGES_PER_CONVERSATION_PER_MINUTE = 8
MAX_NEW_REQUESTS_PER_HOUR = 12
RATE_LIMIT_TTL_SECONDS = 3 * 60 * 60
MAX_TRANSACTION_REVIEW_COMMENT_LENGTH = 1000
dynamodb = boto3.resource("dynamodb")


def _table():
    if not MESSAGING_TABLE_NAME:
        raise RuntimeError("USER_MESSAGING_TABLE is not configured")
    return dynamodb.Table(MESSAGING_TABLE_NAME)


def _conversation_id(user_a_id, user_b_id):
    first, second = sorted([str(user_a_id), str(user_b_id)])
    return f"dm#{first}#{second}"


def _showroom_transaction_conversation_id(showroom_post_id, seller_user_id, buyer_user_id):
    return f"tx#{showroom_post_id}#{seller_user_id}#{buyer_user_id}"


def _conversation_pk(conversation_id):
    return f"CONV#{conversation_id}"


def _user_pk(user_id):
    return f"USER#{user_id}"


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _epoch_now():
    return int(time.time())


def _to_dynamo_number(value):
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    return value


def _message_sort_key(created_at, message_id):
    return f"MSG#{created_at}#{message_id}"


def _message_to_response(item):
    return {
        "id": item.get("messageId"),
        "senderId": item.get("senderId"),
        "text": item.get("text"),
        "createdAt": item.get("createdAt"),
        "sortKey": item.get("sk"),
    }


def _websocket_client():
    if not MESSAGING_WS_CALLBACK_URL:
        raise RuntimeError("MESSAGING_WS_CALLBACK_URL is not configured")
    return boto3.client("apigatewaymanagementapi", endpoint_url=MESSAGING_WS_CALLBACK_URL)


def _get_relationship_or_raise(actor_sub, target_user_id):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    target_user = user_repository.get_user_by_id(target_user_id)
    if not target_user:
        raise ValueError("User not found")

    relationship = user_repository.get_follow_status(actor["id"], target_user_id)
    return actor, target_user, relationship


def _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=None):
    actor, target_user, relationship = _get_relationship_or_raise(actor_sub, target_user_id)
    actor_id = str(actor["id"])
    target_id = str(target_user["id"])

    context = {
        "actor": actor,
        "target_user": target_user,
        "relationship": relationship,
        "actor_id": actor_id,
        "target_id": target_id,
        "conversation_type": "direct",
        "conversation_id": _conversation_id(actor_id, target_id),
        "showroom_post": None,
        "showroom_post_id": None,
        "seller_user_id": None,
        "buyer_user_id": None,
    }

    if not showroom_post_id:
        return context

    showroom_post = showroom_repository.get_showroom_post(showroom_post_id, actor_id=actor_id)
    if not showroom_post:
        raise ValueError("Selling post not found")
    if showroom_post.get("post_type") != "selling":
        raise ValueError("Only selling posts support transaction chats")

    seller_user_id = str((showroom_post.get("author") or {}).get("id") or "")
    if not seller_user_id:
        raise ValueError("Selling post is missing a seller")
    if seller_user_id not in {actor_id, target_id}:
        raise PermissionError("Transaction chats must include the seller of the listing.")

    buyer_user_id = target_id if seller_user_id == actor_id else actor_id
    if buyer_user_id == seller_user_id:
        raise ValueError("Seller and buyer cannot be the same user")

    context.update({
        "conversation_type": "showroom_transaction",
        "conversation_id": _showroom_transaction_conversation_id(showroom_post_id, seller_user_id, buyer_user_id),
        "showroom_post": showroom_post,
        "showroom_post_id": showroom_post_id,
        "seller_user_id": seller_user_id,
        "buyer_user_id": buyer_user_id,
    })
    return context


def _get_conversation_meta(conversation_id):
    return _table().get_item(
        Key={
            "pk": _conversation_pk(conversation_id),
            "sk": "META",
        }
    ).get("Item")


def _get_conversation_message_page(conversation_id, limit=DEFAULT_THREAD_PAGE_SIZE, before=None):
    page_limit = max(1, min(limit, MAX_THREAD_PAGE_SIZE))
    query_kwargs = {
        "KeyConditionExpression": Key("pk").eq(_conversation_pk(conversation_id)),
        "ScanIndexForward": False,
        "Limit": page_limit + 5,
    }
    if before:
        query_kwargs["KeyConditionExpression"] = (
            Key("pk").eq(_conversation_pk(conversation_id)) & Key("sk").lt(before)
        )

    response = _table().query(**query_kwargs)
    all_message_items = [
        item
        for item in response.get("Items", [])
        if item.get("itemType") == "MESSAGE"
    ]
    has_more = len(all_message_items) > page_limit or bool(response.get("LastEvaluatedKey"))
    message_items = all_message_items[:page_limit]
    next_cursor = message_items[-1].get("sk") if has_more and message_items else None
    message_items.reverse()
    return message_items, next_cursor, has_more


def _get_connection_items(user_id):
    response = _table().query(
        KeyConditionExpression=Key("pk").eq(_user_pk(user_id)) & Key("sk").begins_with("WS#"),
    )
    return response.get("Items", [])


def _conversation_mode(relationship, meta):
    if relationship.get("blocking"):
        return "blocking"
    if relationship.get("blockedBy"):
        return "blocked_by"
    if meta and meta.get("conversationType") == "showroom_transaction":
        return "transaction"
    if relationship.get("isFriend"):
        return "friend"
    if meta and meta.get("pendingRequest"):
        return "request_pending"
    if meta:
        return "direct_unlocked"
    return "request_available"


def _can_send(actor_id, relationship, meta):
    if relationship.get("blocking"):
        return False, "You have blocked this collector."
    if relationship.get("blockedBy"):
        return False, "This collector has blocked you."
    if meta and meta.get("conversationType") == "showroom_transaction":
        return True, None
    if relationship.get("isFriend"):
        return True, None
    if meta and meta.get("pendingRequest") and meta.get("requestLockedUserId") == actor_id:
        return False, "You already sent an intro message. Wait for a reply before sending another."
    return True, None


def _rate_limit_pk(user_id):
    return f"RATE#{user_id}"


def _increment_rate_counter(user_id, bucket_key, ttl_seconds=RATE_LIMIT_TTL_SECONDS):
    response = _table().update_item(
        Key={
            "pk": _rate_limit_pk(user_id),
            "sk": bucket_key,
        },
        UpdateExpression="ADD #count :inc SET itemType = :item_type, expiresAt = :expires_at, updatedAt = :updated_at",
        ExpressionAttributeNames={
            "#count": "count",
        },
        ExpressionAttributeValues={
            ":inc": 1,
            ":item_type": "RATE_LIMIT",
            ":expires_at": _epoch_now() + ttl_seconds,
            ":updated_at": _iso_now(),
        },
        ReturnValues="ALL_NEW",
    )
    return int((response.get("Attributes") or {}).get("count", 0) or 0)


def _enforce_rate_limits(actor_id, target_id, relationship, meta):
    current_time = datetime.now(timezone.utc)
    minute_bucket = current_time.strftime("%Y%m%d%H%M")
    hour_bucket = current_time.strftime("%Y%m%d%H")
    conversation_id = _conversation_id(actor_id, target_id)

    message_count = _increment_rate_counter(actor_id, f"MSG#{minute_bucket}")
    if message_count > MAX_MESSAGES_PER_MINUTE:
        raise PermissionError("You are sending messages too quickly. Please wait a minute and try again.")

    conversation_count = _increment_rate_counter(actor_id, f"CONVMSG#{conversation_id}#{minute_bucket}")
    if conversation_count > MAX_MESSAGES_PER_CONVERSATION_PER_MINUTE:
        raise PermissionError("You are sending too many messages in this conversation too quickly. Please slow down.")

    if not relationship.get("isFriend") and not meta:
        intro_count = _increment_rate_counter(actor_id, f"INTRO#{hour_bucket}")
        if intro_count > MAX_NEW_REQUESTS_PER_HOUR:
            raise PermissionError("You have reached the limit for starting new direct message requests this hour.")


def _send_ws_event(user_id, payload):
    try:
        client = _websocket_client()
    except RuntimeError:
        return

    connection_items = _get_connection_items(user_id)
    print(
        "messaging websocket delivery attempt",
        json.dumps(
            {
                "userId": user_id,
                "payloadType": payload.get("type"),
                "connectionCount": len(connection_items),
            }
        ),
    )

    for item in connection_items:
        connection_id = item.get("connectionId")
        if not connection_id:
            continue

        try:
            client.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(payload).encode("utf-8"),
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code == "GoneException":
                _table().delete_item(
                    Key={
                        "pk": _user_pk(user_id),
                        "sk": f"WS#{connection_id}",
                    }
                )
                _table().delete_item(
                    Key={
                        "pk": f"CONN#{connection_id}",
                        "sk": "META",
                    }
                )
                continue
            print(
                "messaging websocket post_to_connection failed",
                json.dumps(
                    {
                        "userId": user_id,
                        "connectionId": connection_id,
                        "code": code,
                        "payloadType": payload.get("type"),
                    }
                ),
            )
            continue
        except Exception as error:
            print(
                "messaging websocket unexpected failure",
                json.dumps(
                    {
                        "userId": user_id,
                        "connectionId": connection_id,
                        "payloadType": payload.get("type"),
                        "error": str(error),
                    }
                ),
            )
            continue
        else:
            print(
                "messaging websocket delivered",
                json.dumps(
                    {
                        "userId": user_id,
                        "connectionId": connection_id,
                        "payloadType": payload.get("type"),
                    }
                ),
            )


def _build_conversation_response(actor_id, target_user_id, relationship, meta, messages, next_cursor=None, has_more=False):
    can_send, lock_reason = _can_send(actor_id, relationship, meta)
    showroom_context = None
    if meta and meta.get("conversationType") == "showroom_transaction":
        showroom_context = {
            "postId": meta.get("showroomPostId"),
            "title": meta.get("showroomTitle"),
            "imageUrl": meta.get("showroomCoverImageUrl"),
            "price": float(meta.get("showroomPrice")) if isinstance(meta.get("showroomPrice"), Decimal) else meta.get("showroomPrice"),
            "currency": meta.get("showroomCurrency"),
            "transactionStatus": meta.get("transactionStatus") or "available",
            "sellerUserId": meta.get("sellerUserId"),
            "buyerUserId": meta.get("buyerUserId"),
        }
    return {
        "conversationId": meta.get("conversationId") if meta else _conversation_id(actor_id, target_user_id),
        "partnerUserId": target_user_id,
        "mode": _conversation_mode(relationship, meta),
        "conversationType": (meta or {}).get("conversationType") or "direct",
        "canSend": can_send,
        "lockReason": lock_reason,
        "isFriend": relationship.get("isFriend", False),
        "blocking": relationship.get("blocking", False),
        "blockedBy": relationship.get("blockedBy", False),
        "canSendMedia": False,
        "hasConversation": meta is not None,
        "unreadCount": meta.get("unreadCount", 0) if meta else 0,
        "showroomContext": showroom_context,
        "canSellerUpdateTransactionStatus": bool(
            showroom_context
            and actor_id == showroom_context.get("sellerUserId")
        ),
        "transactionReview": _build_transaction_review_payload(
            meta,
            actor_id,
            target_user_id,
        ),
        "messages": [_message_to_response(item) for item in messages],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


def _build_transaction_review_payload(meta, actor_id, target_user_id):
    if not meta or meta.get("conversationType") != "showroom_transaction":
        return None

    transaction_status = meta.get("transactionStatus") or "available"
    seller_user_id = str(meta.get("sellerUserId") or "")
    buyer_user_id = str(meta.get("buyerUserId") or "")
    showroom_post_id = meta.get("showroomPostId")
    if not showroom_post_id or not seller_user_id or not buyer_user_id:
        return None

    reviews = showroom_repository.list_showroom_transaction_reviews(
        showroom_post_id,
        seller_user_id,
        buyer_user_id,
    )
    viewer_review = next((review for review in reviews if (review.get("reviewer") or {}).get("id") == actor_id), None)
    partner_review = next((review for review in reviews if (review.get("reviewer") or {}).get("id") == target_user_id), None)

    can_leave_review = transaction_status == "sold" and actor_id in {seller_user_id, buyer_user_id} and viewer_review is None
    return {
        "transactionStatus": transaction_status,
        "viewerReview": viewer_review,
        "partnerReview": partner_review,
        "canLeaveReview": can_leave_review,
    }


def get_direct_conversation(actor_sub, target_user_id, limit=DEFAULT_THREAD_PAGE_SIZE, before=None):
    context = _resolve_conversation_context(actor_sub, target_user_id)
    actor_id = context["actor_id"]
    conversation_id = context["conversation_id"]
    meta = _get_conversation_meta(conversation_id)
    messages, next_cursor, has_more = _get_conversation_message_page(
        conversation_id,
        limit=limit,
        before=before,
    )
    inbox_item = _table().get_item(
        Key={
            "pk": _user_pk(actor_id),
            "sk": f"CONV#{conversation_id}",
        }
    ).get("Item")
    if meta is None:
        meta = {}
    meta = dict(meta)
    meta["unreadCount"] = int((inbox_item or {}).get("unreadCount", 0) or 0)
    return _build_conversation_response(
        actor_id,
        target_user_id,
        context["relationship"],
        meta,
        messages,
        next_cursor=next_cursor,
        has_more=has_more,
    )


def get_showroom_transaction_conversation(actor_sub, target_user_id, showroom_post_id, limit=DEFAULT_THREAD_PAGE_SIZE, before=None):
    context = _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=showroom_post_id)
    actor_id = context["actor_id"]
    conversation_id = context["conversation_id"]
    meta = _get_conversation_meta(conversation_id)
    messages, next_cursor, has_more = _get_conversation_message_page(
        conversation_id,
        limit=limit,
        before=before,
    )
    inbox_item = _table().get_item(
        Key={
            "pk": _user_pk(actor_id),
            "sk": f"CONV#{conversation_id}",
        }
    ).get("Item")
    if meta is None:
        showroom_post = context["showroom_post"] or {}
        cover_image = None
        images = showroom_post.get("images") or []
        if images:
            cover_image = (images[0] or {}).get("imageUrl") or (images[0] or {}).get("image_url")
        selling_details = showroom_post.get("selling_details") or {}
        meta = {
            "conversationId": conversation_id,
            "conversationType": "showroom_transaction",
            "showroomPostId": showroom_post_id,
            "showroomTitle": showroom_post.get("title"),
            "showroomCoverImageUrl": cover_image,
            "showroomPrice": _to_dynamo_number(selling_details.get("price")),
            "showroomCurrency": selling_details.get("currency"),
            "transactionStatus": selling_details.get("sellingStatus") or selling_details.get("selling_status") or "available",
            "sellerUserId": context["seller_user_id"],
            "buyerUserId": context["buyer_user_id"],
            "unreadCount": 0,
        }
    else:
        meta = dict(meta)
        meta["unreadCount"] = int((inbox_item or {}).get("unreadCount", 0) or 0)

    return _build_conversation_response(
        actor_id,
        target_user_id,
        context["relationship"],
        meta,
        messages,
        next_cursor=next_cursor,
        has_more=has_more,
    )


def create_socket_ticket(actor_sub):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")
    if not MESSAGING_WS_URL:
        raise RuntimeError("MESSAGING_WS_URL is not configured")

    ticket = str(uuid.uuid4())
    expires_at = _epoch_now() + 60
    _table().put_item(
        Item={
            "pk": f"TICKET#{ticket}",
            "sk": "META",
            "itemType": "WS_TICKET",
            "userId": str(actor["id"]),
            "expiresAt": expires_at,
            "createdAt": _iso_now(),
        }
    )
    return {
        "ticket": ticket,
        "websocketUrl": MESSAGING_WS_URL,
        "expiresAt": expires_at,
    }


def list_direct_conversations(actor_sub):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    actor_id = str(actor["id"])
    response = _table().query(
        KeyConditionExpression=Key("pk").eq(_user_pk(actor_id)),
        ScanIndexForward=False,
        Limit=50,
    )
    items = [
        item
        for item in response.get("Items", [])
        if item.get("itemType") == "USER_CONVERSATION" and item.get("partnerUserId")
    ]
    partner_ids = [item.get("partnerUserId") for item in items if item.get("partnerUserId")]
    partner_map = user_repository.get_users_by_ids(partner_ids)

    results = []
    total_unread_count = 0
    for item in items:
        partner_id = item.get("partnerUserId")
        relationship = user_repository.get_follow_status(actor_id, partner_id) if partner_id else {}
        partner = partner_map.get(partner_id, {})
        unread_count = int(item.get("unreadCount", 0) or 0)
        total_unread_count += unread_count
        results.append({
            "conversationId": item.get("conversationId"),
            "partnerUserId": partner_id,
            "conversationType": item.get("conversationType") or "direct",
            "partner": {
                "id": partner.get("id"),
                "username": partner.get("username"),
                "profileImageUrl": partner.get("profile_image_url"),
                "bio": partner.get("bio"),
            },
            "lastMessageAt": item.get("lastMessageAt"),
            "lastMessagePreview": item.get("lastMessagePreview"),
            "lastMessageSenderId": item.get("lastMessageSenderId"),
            "pendingRequest": item.get("pendingRequest", False),
            "unreadCount": unread_count,
            "mode": _conversation_mode(relationship, item),
            "isFriend": relationship.get("isFriend", False),
            "blocking": relationship.get("blocking", False),
            "blockedBy": relationship.get("blockedBy", False),
            "canSendMedia": False,
            "showroomContext": {
                "postId": item.get("showroomPostId"),
                "title": item.get("showroomTitle"),
                "imageUrl": item.get("showroomCoverImageUrl"),
                "price": float(item.get("showroomPrice")) if isinstance(item.get("showroomPrice"), Decimal) else item.get("showroomPrice"),
                "currency": item.get("showroomCurrency"),
                "transactionStatus": item.get("transactionStatus") or "available",
                "sellerUserId": item.get("sellerUserId"),
                "buyerUserId": item.get("buyerUserId"),
            } if item.get("conversationType") == "showroom_transaction" else None,
        })

    results.sort(key=lambda item: item.get("lastMessageAt") or "", reverse=True)

    return {
        "items": results,
        "totalUnreadCount": total_unread_count,
    }


def list_direct_conversation_partners(actor_sub):
    conversations = list_direct_conversations(actor_sub)
    return [
        {
            "userId": item.get("partnerUserId"),
            "username": (item.get("partner") or {}).get("username"),
            "profileImageUrl": (item.get("partner") or {}).get("profileImageUrl"),
            "blocking": item.get("blocking", False),
            "blockedBy": item.get("blockedBy", False),
        }
        for item in conversations.get("items", [])
        if item.get("partnerUserId")
    ]


def list_showroom_transaction_history(actor_sub, role="selling", limit=20, offset=0):
    actor = user_repository.get_user_by_sub(actor_sub)
    if not actor:
        raise ValueError("Viewer not found")

    actor_id = str(actor["id"])
    normalized_role = str(role or "selling").strip().lower()
    if normalized_role not in {"selling", "buying"}:
        raise ValueError("Invalid order history role")

    safe_limit = min(max(int(limit or 20), 1), 50)
    safe_offset = max(int(offset or 0), 0)

    response = _table().query(
        KeyConditionExpression=Key("pk").eq(_user_pk(actor_id)),
        ScanIndexForward=False,
    )
    items = [
        item
        for item in response.get("Items", [])
        if item.get("itemType") == "USER_CONVERSATION"
        and item.get("conversationType") == "showroom_transaction"
        and item.get("showroomPostId")
    ]

    filtered_items = []
    for item in items:
        seller_user_id = str(item.get("sellerUserId") or "")
        buyer_user_id = str(item.get("buyerUserId") or "")
        if normalized_role == "selling" and seller_user_id != actor_id:
            continue
        if normalized_role == "buying" and buyer_user_id != actor_id:
            continue
        filtered_items.append(item)

    filtered_items.sort(key=lambda item: item.get("lastMessageAt") or "", reverse=True)
    total = len(filtered_items)
    page_items = filtered_items[safe_offset:safe_offset + safe_limit]

    partner_ids = [item.get("partnerUserId") for item in page_items if item.get("partnerUserId")]
    partner_map = user_repository.get_users_by_ids(partner_ids)

    return {
        "items": [
            {
                "conversationId": item.get("conversationId"),
                "partnerUserId": item.get("partnerUserId"),
                "partner": {
                    "id": partner_map.get(item.get("partnerUserId"), {}).get("id"),
                    "username": partner_map.get(item.get("partnerUserId"), {}).get("username"),
                    "profileImageUrl": partner_map.get(item.get("partnerUserId"), {}).get("profile_image_url"),
                    "bio": partner_map.get(item.get("partnerUserId"), {}).get("bio"),
                },
                "showroomContext": {
                    "postId": item.get("showroomPostId"),
                    "title": item.get("showroomTitle"),
                    "imageUrl": item.get("showroomCoverImageUrl"),
                    "price": float(item.get("showroomPrice")) if isinstance(item.get("showroomPrice"), Decimal) else item.get("showroomPrice"),
                    "currency": item.get("showroomCurrency"),
                    "transactionStatus": item.get("transactionStatus") or "available",
                    "sellerUserId": item.get("sellerUserId"),
                    "buyerUserId": item.get("buyerUserId"),
                },
                "lastMessageAt": item.get("lastMessageAt"),
                "lastMessagePreview": item.get("lastMessagePreview"),
                "lastMessageSenderId": item.get("lastMessageSenderId"),
                "role": normalized_role,
                "unreadCount": int(item.get("unreadCount", 0) or 0),
                "reviewState": _build_order_history_review_state(
                    actor_id,
                    item.get("showroomPostId"),
                    item.get("sellerUserId"),
                    item.get("buyerUserId"),
                ),
            }
            for item in page_items
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "role": normalized_role,
    }


def _build_order_history_review_state(actor_id, showroom_post_id, seller_user_id, buyer_user_id):
    if not showroom_post_id or not seller_user_id or not buyer_user_id:
        return None

    reviews = showroom_repository.list_showroom_transaction_reviews(
        showroom_post_id,
        seller_user_id,
        buyer_user_id,
    )
    viewer_review = next((review for review in reviews if (review.get("reviewer") or {}).get("id") == actor_id), None)
    partner_review = next((review for review in reviews if (review.get("reviewer") or {}).get("id") != actor_id), None)
    return {
        "viewerHasReviewed": viewer_review is not None,
        "partnerHasReviewed": partner_review is not None,
    }


def mark_direct_conversation_read(actor_sub, target_user_id):
    context = _resolve_conversation_context(actor_sub, target_user_id)
    actor_id = context["actor_id"]
    conversation_id = context["conversation_id"]
    inbox_key = {
        "pk": _user_pk(actor_id),
        "sk": f"CONV#{conversation_id}",
    }

    _table().update_item(
        Key=inbox_key,
        UpdateExpression="SET unreadCount = :zero, updatedAt = :updated_at",
        ExpressionAttributeValues={
            ":zero": 0,
            ":updated_at": _iso_now(),
        },
    )

    _send_ws_event(
        actor_id,
        {
            "type": "conversation.read",
            "partnerUserId": target_user_id,
            "conversationId": conversation_id,
            "conversationType": "direct",
        },
    )

    return {"message": "read"}


def mark_showroom_transaction_read(actor_sub, target_user_id, showroom_post_id):
    context = _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=showroom_post_id)
    actor_id = context["actor_id"]
    conversation_id = context["conversation_id"]
    inbox_key = {
        "pk": _user_pk(actor_id),
        "sk": f"CONV#{conversation_id}",
    }

    _table().update_item(
        Key=inbox_key,
        UpdateExpression="SET unreadCount = :zero, updatedAt = :updated_at",
        ExpressionAttributeValues={
            ":zero": 0,
            ":updated_at": _iso_now(),
        },
    )

    _send_ws_event(
        actor_id,
        {
            "type": "conversation.read",
            "partnerUserId": target_user_id,
            "conversationId": conversation_id,
            "conversationType": "showroom_transaction",
            "showroomPostId": showroom_post_id,
        },
    )

    return {"message": "read"}


def send_direct_message(actor_sub, target_user_id, text):
    context = _resolve_conversation_context(actor_sub, target_user_id)
    actor_id = context["actor_id"]
    target_id = context["target_id"]
    relationship = context["relationship"]

    body = (text or "").strip()
    if not body:
        raise ValueError("Message text is required")

    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message is too long. Keep it under {MAX_MESSAGE_LENGTH} characters.")

    conversation_id = context["conversation_id"]
    meta = _get_conversation_meta(conversation_id)
    existing_messages, _, _ = _get_conversation_message_page(conversation_id, limit=MAX_THREAD_PAGE_SIZE)
    actor_inbox_key = {
        "pk": _user_pk(actor_id),
        "sk": f"CONV#{conversation_id}",
    }
    target_inbox_key = {
        "pk": _user_pk(target_id),
        "sk": f"CONV#{conversation_id}",
    }
    actor_inbox_existing = _table().get_item(Key=actor_inbox_key).get("Item")
    target_inbox_existing = _table().get_item(Key=target_inbox_key).get("Item")

    can_send, lock_reason = _can_send(actor_id, relationship, meta)
    if not can_send:
        raise PermissionError(lock_reason)
    _enforce_rate_limits(actor_id, target_id, relationship, meta)

    created_at = _iso_now()
    message_id = str(uuid.uuid4())
    message_item = {
        "pk": _conversation_pk(conversation_id),
        "sk": _message_sort_key(created_at, message_id),
        "itemType": "MESSAGE",
        "conversationId": conversation_id,
        "messageId": message_id,
        "senderId": actor_id,
        "recipientId": target_id,
        "text": body,
        "createdAt": created_at,
    }

    if not meta:
        meta = {
            "pk": _conversation_pk(conversation_id),
            "sk": "META",
            "itemType": "CONVERSATION",
            "conversationId": conversation_id,
            "conversationType": "direct",
            "participantIds": [actor_id, target_id],
            "initiatorUserId": actor_id,
            "targetUserId": target_id,
            "pendingRequest": not relationship.get("isFriend"),
            "requestLockedUserId": None if relationship.get("isFriend") else actor_id,
            "lastMessageAt": created_at,
            "lastMessagePreview": body[:180],
            "lastMessageSenderId": actor_id,
            "updatedAt": created_at,
        }
    else:
        meta["lastMessageAt"] = created_at
        meta["lastMessagePreview"] = body[:180]
        meta["lastMessageSenderId"] = actor_id
        meta["updatedAt"] = created_at
        if not relationship.get("isFriend") and meta.get("pendingRequest") and meta.get("requestLockedUserId") != actor_id:
            meta["pendingRequest"] = False
            meta["requestLockedUserId"] = None
        if relationship.get("isFriend"):
            meta["pendingRequest"] = False
            meta["requestLockedUserId"] = None

    actor_inbox = {
        "pk": actor_inbox_key["pk"],
        "sk": actor_inbox_key["sk"],
        "itemType": "USER_CONVERSATION",
        "conversationId": conversation_id,
        "conversationType": "direct",
        "partnerUserId": target_id,
        "lastMessageAt": created_at,
        "lastMessagePreview": body[:180],
        "lastMessageSenderId": actor_id,
        "pendingRequest": meta.get("pendingRequest", False),
        "unreadCount": 0,
        "mode": _conversation_mode(relationship, meta),
        "updatedAt": created_at,
    }
    target_inbox = {
        "pk": target_inbox_key["pk"],
        "sk": target_inbox_key["sk"],
        "itemType": "USER_CONVERSATION",
        "conversationId": conversation_id,
        "conversationType": "direct",
        "partnerUserId": actor_id,
        "lastMessageAt": created_at,
        "lastMessagePreview": body[:180],
        "lastMessageSenderId": actor_id,
        "pendingRequest": meta.get("pendingRequest", False),
        "unreadCount": int((target_inbox_existing or {}).get("unreadCount", 0) or 0) + 1,
        "mode": _conversation_mode(relationship, meta),
        "updatedAt": created_at,
    }

    table = _table()
    table.put_item(Item=meta)
    table.put_item(Item=message_item)
    table.put_item(Item=actor_inbox)
    table.put_item(Item=target_inbox)

    updated_messages = existing_messages + [message_item]
    actor_meta = dict(meta)
    actor_meta["unreadCount"] = int((actor_inbox_existing or {}).get("unreadCount", 0) or 0)
    actor_meta["unreadCount"] = 0
    _send_ws_event(
        actor_id,
        {
            "type": "message.updated",
            "conversationId": conversation_id,
            "partnerUserId": target_id,
            "senderId": actor_id,
            "conversationType": "direct",
        },
    )
    _send_ws_event(
        target_id,
        {
            "type": "message.updated",
            "conversationId": conversation_id,
            "partnerUserId": actor_id,
            "senderId": actor_id,
            "conversationType": "direct",
        },
    )
    trimmed_messages = updated_messages[-MAX_THREAD_PAGE_SIZE:]
    return _build_conversation_response(
        actor_id,
        target_id,
        relationship,
        actor_meta,
        trimmed_messages,
        next_cursor=trimmed_messages[0].get("sk") if len(trimmed_messages) == MAX_THREAD_PAGE_SIZE else None,
        has_more=len(updated_messages) > len(trimmed_messages),
    )


def send_showroom_transaction_message(actor_sub, target_user_id, showroom_post_id, text):
    context = _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=showroom_post_id)
    actor_id = context["actor_id"]
    target_id = context["target_id"]
    relationship = context["relationship"]
    showroom_post = context["showroom_post"] or {}

    body = (text or "").strip()
    if not body:
        raise ValueError("Message text is required")
    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message is too long. Keep it under {MAX_MESSAGE_LENGTH} characters.")

    conversation_id = context["conversation_id"]
    meta = _get_conversation_meta(conversation_id)
    existing_messages, _, _ = _get_conversation_message_page(conversation_id, limit=MAX_THREAD_PAGE_SIZE)
    actor_inbox_key = {
        "pk": _user_pk(actor_id),
        "sk": f"CONV#{conversation_id}",
    }
    target_inbox_key = {
        "pk": _user_pk(target_id),
        "sk": f"CONV#{conversation_id}",
    }
    actor_inbox_existing = _table().get_item(Key=actor_inbox_key).get("Item")
    target_inbox_existing = _table().get_item(Key=target_inbox_key).get("Item")

    effective_meta = meta or {
        "conversationType": "showroom_transaction",
    }
    can_send, lock_reason = _can_send(actor_id, relationship, effective_meta)
    if not can_send:
        raise PermissionError(lock_reason)
    _enforce_rate_limits(actor_id, target_id, relationship, effective_meta)

    created_at = _iso_now()
    message_id = str(uuid.uuid4())
    message_item = {
        "pk": _conversation_pk(conversation_id),
        "sk": _message_sort_key(created_at, message_id),
        "itemType": "MESSAGE",
        "conversationId": conversation_id,
        "messageId": message_id,
        "senderId": actor_id,
        "recipientId": target_id,
        "text": body,
        "createdAt": created_at,
    }

    selling_details = showroom_post.get("selling_details") or {}
    cover_image = None
    images = showroom_post.get("images") or []
    if images:
        cover_image = (images[0] or {}).get("imageUrl") or (images[0] or {}).get("image_url")

    if not meta:
        meta = {
            "pk": _conversation_pk(conversation_id),
            "sk": "META",
            "itemType": "CONVERSATION",
            "conversationId": conversation_id,
            "conversationType": "showroom_transaction",
            "participantIds": [actor_id, target_id],
            "initiatorUserId": actor_id,
            "targetUserId": target_id,
            "pendingRequest": False,
            "requestLockedUserId": None,
            "showroomPostId": showroom_post_id,
            "showroomTitle": showroom_post.get("title"),
            "showroomCoverImageUrl": cover_image,
            "showroomPrice": _to_dynamo_number(selling_details.get("price")),
            "showroomCurrency": selling_details.get("currency"),
            "transactionStatus": selling_details.get("sellingStatus") or selling_details.get("selling_status") or "available",
            "sellerUserId": context["seller_user_id"],
            "buyerUserId": context["buyer_user_id"],
            "lastMessageAt": created_at,
            "lastMessagePreview": body[:180],
            "lastMessageSenderId": actor_id,
            "updatedAt": created_at,
        }
    else:
        meta["lastMessageAt"] = created_at
        meta["lastMessagePreview"] = body[:180]
        meta["lastMessageSenderId"] = actor_id
        meta["updatedAt"] = created_at

    actor_inbox = {
        "pk": actor_inbox_key["pk"],
        "sk": actor_inbox_key["sk"],
        "itemType": "USER_CONVERSATION",
        "conversationId": conversation_id,
        "conversationType": "showroom_transaction",
        "partnerUserId": target_id,
        "showroomPostId": showroom_post_id,
        "showroomTitle": meta.get("showroomTitle"),
        "showroomCoverImageUrl": meta.get("showroomCoverImageUrl"),
        "showroomPrice": meta.get("showroomPrice"),
        "showroomCurrency": meta.get("showroomCurrency"),
        "transactionStatus": meta.get("transactionStatus") or "available",
        "sellerUserId": meta.get("sellerUserId"),
        "buyerUserId": meta.get("buyerUserId"),
        "lastMessageAt": created_at,
        "lastMessagePreview": body[:180],
        "lastMessageSenderId": actor_id,
        "pendingRequest": False,
        "unreadCount": 0,
        "mode": _conversation_mode(relationship, meta),
        "updatedAt": created_at,
    }
    target_inbox = {
        "pk": target_inbox_key["pk"],
        "sk": target_inbox_key["sk"],
        "itemType": "USER_CONVERSATION",
        "conversationId": conversation_id,
        "conversationType": "showroom_transaction",
        "partnerUserId": actor_id,
        "showroomPostId": showroom_post_id,
        "showroomTitle": meta.get("showroomTitle"),
        "showroomCoverImageUrl": meta.get("showroomCoverImageUrl"),
        "showroomPrice": meta.get("showroomPrice"),
        "showroomCurrency": meta.get("showroomCurrency"),
        "transactionStatus": meta.get("transactionStatus") or "available",
        "sellerUserId": meta.get("sellerUserId"),
        "buyerUserId": meta.get("buyerUserId"),
        "lastMessageAt": created_at,
        "lastMessagePreview": body[:180],
        "lastMessageSenderId": actor_id,
        "pendingRequest": False,
        "unreadCount": int((target_inbox_existing or {}).get("unreadCount", 0) or 0) + 1,
        "mode": _conversation_mode(relationship, meta),
        "updatedAt": created_at,
    }

    table = _table()
    table.put_item(Item=meta)
    table.put_item(Item=message_item)
    table.put_item(Item=actor_inbox)
    table.put_item(Item=target_inbox)

    updated_messages = existing_messages + [message_item]
    actor_meta = dict(meta)
    actor_meta["unreadCount"] = 0
    _send_ws_event(
        actor_id,
        {
            "type": "message.updated",
            "conversationId": conversation_id,
            "partnerUserId": target_id,
            "senderId": actor_id,
            "conversationType": "showroom_transaction",
            "showroomPostId": showroom_post_id,
        },
    )
    _send_ws_event(
        target_id,
        {
            "type": "message.updated",
            "conversationId": conversation_id,
            "partnerUserId": actor_id,
            "senderId": actor_id,
            "conversationType": "showroom_transaction",
            "showroomPostId": showroom_post_id,
        },
    )
    trimmed_messages = updated_messages[-MAX_THREAD_PAGE_SIZE:]
    return _build_conversation_response(
        actor_id,
        target_id,
        relationship,
        actor_meta,
        trimmed_messages,
        next_cursor=trimmed_messages[0].get("sk") if len(trimmed_messages) == MAX_THREAD_PAGE_SIZE else None,
        has_more=len(updated_messages) > len(trimmed_messages),
    )


def update_showroom_transaction_status(actor_sub, target_user_id, showroom_post_id, transaction_status):
    context = _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=showroom_post_id)
    actor_id = context["actor_id"]
    if actor_id != context["seller_user_id"]:
        raise PermissionError("Only the seller can update transaction status from chat.")

    normalized_status = str(transaction_status or "").strip().lower()
    if normalized_status not in {"available", "pending", "sold"}:
        raise ValueError("Invalid transaction status")

    conversation_id = context["conversation_id"]
    meta = _get_conversation_meta(conversation_id)
    if not meta:
        raise ValueError("Start the transaction chat before updating its status.")

    updated_at = _iso_now()
    _table().update_item(
        Key={
            "pk": _conversation_pk(conversation_id),
            "sk": "META",
        },
        UpdateExpression="SET transactionStatus = :status, updatedAt = :updated_at",
        ExpressionAttributeValues={
            ":status": normalized_status,
            ":updated_at": updated_at,
        },
    )
    for user_id, partner_id in (
        (context["seller_user_id"], context["buyer_user_id"]),
        (context["buyer_user_id"], context["seller_user_id"]),
    ):
        _table().update_item(
            Key={
                "pk": _user_pk(user_id),
                "sk": f"CONV#{conversation_id}",
            },
            UpdateExpression="SET transactionStatus = :status, updatedAt = :updated_at",
            ExpressionAttributeValues={
                ":status": normalized_status,
                ":updated_at": updated_at,
            },
        )

    showroom_repository.update_showroom_selling_status(
        post_id=showroom_post_id,
        user_id=context["seller_user_id"],
        selling_status=normalized_status,
    )

    for user_id, partner_id in (
        (context["seller_user_id"], context["buyer_user_id"]),
        (context["buyer_user_id"], context["seller_user_id"]),
    ):
        _send_ws_event(
            user_id,
            {
                "type": "conversation.transaction_status_updated",
                "conversationId": conversation_id,
                "partnerUserId": partner_id,
                "conversationType": "showroom_transaction",
                "showroomPostId": showroom_post_id,
                "transactionStatus": normalized_status,
            },
        )

    return get_showroom_transaction_conversation(actor_sub, target_user_id, showroom_post_id)


def create_showroom_transaction_review(actor_sub, target_user_id, showroom_post_id, rating, comment):
    context = _resolve_conversation_context(actor_sub, target_user_id, showroom_post_id=showroom_post_id)
    actor_id = context["actor_id"]
    target_id = context["target_id"]
    if actor_id not in {context["seller_user_id"], context["buyer_user_id"]}:
        raise PermissionError("Only the seller or buyer can review this transaction.")

    meta = _get_conversation_meta(context["conversation_id"])
    if not meta:
        raise ValueError("Start the transaction chat before leaving a review.")
    if (meta.get("transactionStatus") or "available") != "sold":
        raise ValueError("Reviews unlock only after the transaction is marked sold.")

    normalized_rating = int(rating or 0)
    normalized_comment = (comment or "").strip()
    if normalized_rating < 1 or normalized_rating > 5:
        raise ValueError("Rating must be between 1 and 5.")
    if not normalized_comment:
        raise ValueError("Review comment is required.")
    if len(normalized_comment) > MAX_TRANSACTION_REVIEW_COMMENT_LENGTH:
        raise ValueError(f"Review comment is too long. Keep it under {MAX_TRANSACTION_REVIEW_COMMENT_LENGTH} characters.")

    review_id = showroom_repository.create_showroom_transaction_review(
        showroom_post_id=showroom_post_id,
        seller_user_id=context["seller_user_id"],
        buyer_user_id=context["buyer_user_id"],
        reviewer_user_id=actor_id,
        reviewee_user_id=target_id,
        rating=normalized_rating,
        comment=normalized_comment,
    )
    if not review_id:
        raise ValueError("You already submitted a review for this transaction.")

    return get_showroom_transaction_conversation(actor_sub, target_user_id, showroom_post_id)
