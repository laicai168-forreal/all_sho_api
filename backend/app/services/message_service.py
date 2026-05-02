import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.repositories import user_repository


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
dynamodb = boto3.resource("dynamodb")


def _table():
    if not MESSAGING_TABLE_NAME:
        raise RuntimeError("USER_MESSAGING_TABLE is not configured")
    return dynamodb.Table(MESSAGING_TABLE_NAME)


def _conversation_id(user_a_id, user_b_id):
    first, second = sorted([str(user_a_id), str(user_b_id)])
    return f"dm#{first}#{second}"


def _conversation_pk(conversation_id):
    return f"CONV#{conversation_id}"


def _user_pk(user_id):
    return f"USER#{user_id}"


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _epoch_now():
    return int(time.time())


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
    return {
        "conversationId": meta.get("conversationId") if meta else _conversation_id(actor_id, target_user_id),
        "partnerUserId": target_user_id,
        "mode": _conversation_mode(relationship, meta),
        "canSend": can_send,
        "lockReason": lock_reason,
        "isFriend": relationship.get("isFriend", False),
        "blocking": relationship.get("blocking", False),
        "blockedBy": relationship.get("blockedBy", False),
        "canSendMedia": False,
        "hasConversation": meta is not None,
        "unreadCount": meta.get("unreadCount", 0) if meta else 0,
        "messages": [_message_to_response(item) for item in messages],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


def get_direct_conversation(actor_sub, target_user_id, limit=DEFAULT_THREAD_PAGE_SIZE, before=None):
    actor, _, relationship = _get_relationship_or_raise(actor_sub, target_user_id)
    actor_id = str(actor["id"])
    conversation_id = _conversation_id(actor_id, target_user_id)
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
        relationship,
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
        })

    results.sort(key=lambda item: item.get("lastMessageAt") or "", reverse=True)

    return {
        "items": results,
        "totalUnreadCount": total_unread_count,
    }


def mark_direct_conversation_read(actor_sub, target_user_id):
    actor, _, relationship = _get_relationship_or_raise(actor_sub, target_user_id)
    actor_id = str(actor["id"])
    conversation_id = _conversation_id(actor_id, target_user_id)
    inbox_key = {
        "pk": _user_pk(actor_id),
        "sk": f"CONV#{conversation_id}",
    }
    existing_item = _table().get_item(Key=inbox_key).get("Item") or {}

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
        },
    )

    return {"message": "read"}


def send_direct_message(actor_sub, target_user_id, text):
    actor, target_user, relationship = _get_relationship_or_raise(actor_sub, target_user_id)
    actor_id = str(actor["id"])
    target_id = str(target_user["id"])

    body = (text or "").strip()
    if not body:
        raise ValueError("Message text is required")

    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message is too long. Keep it under {MAX_MESSAGE_LENGTH} characters.")

    conversation_id = _conversation_id(actor_id, target_id)
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
        },
    )
    _send_ws_event(
        target_id,
        {
            "type": "message.updated",
            "conversationId": conversation_id,
            "partnerUserId": actor_id,
            "senderId": actor_id,
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
