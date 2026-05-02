import os
import time

import boto3


TABLE_NAME = os.environ["USER_MESSAGING_TABLE"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "body": body,
    }


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    query = event.get("queryStringParameters") or {}
    ticket = query.get("ticket")

    if not ticket:
        print(f"messaging websocket missing ticket connectionId={connection_id}")
        return _response(401, "Missing ticket")

    ticket_item = table.get_item(
        Key={
            "pk": f"TICKET#{ticket}",
            "sk": "META",
        }
    ).get("Item")

    if not ticket_item:
        print(f"messaging websocket invalid ticket connectionId={connection_id}")
        return _response(401, "Invalid ticket")

    if int(ticket_item.get("expiresAt", 0) or 0) < int(time.time()):
        table.delete_item(Key={"pk": f"TICKET#{ticket}", "sk": "META"})
        print(f"messaging websocket expired ticket connectionId={connection_id}")
        return _response(401, "Expired ticket")

    user_id = ticket_item.get("userId")
    connected_at = int(time.time())

    table.put_item(
        Item={
            "pk": f"USER#{user_id}",
            "sk": f"WS#{connection_id}",
            "itemType": "WS_CONNECTION",
            "userId": user_id,
            "connectionId": connection_id,
            "connectedAt": connected_at,
        }
    )
    table.put_item(
        Item={
            "pk": f"CONN#{connection_id}",
            "sk": "META",
            "itemType": "WS_CONNECTION_LOOKUP",
            "userId": user_id,
            "connectionId": connection_id,
            "connectedAt": connected_at,
        }
    )
    table.delete_item(Key={"pk": f"TICKET#{ticket}", "sk": "META"})
    print(f"messaging websocket connected userId={user_id} connectionId={connection_id}")

    return _response(200, "Connected")
