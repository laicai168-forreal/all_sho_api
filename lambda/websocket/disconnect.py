import os

import boto3


TABLE_NAME = os.environ["USER_MESSAGING_TABLE"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    lookup_key = {"pk": f"CONN#{connection_id}", "sk": "META"}
    lookup = table.get_item(Key=lookup_key).get("Item")

    if lookup:
        user_id = lookup.get("userId")
        table.delete_item(
            Key={
                "pk": f"USER#{user_id}",
                "sk": f"WS#{connection_id}",
            }
        )
        table.delete_item(Key=lookup_key)
        print(f"messaging websocket disconnected userId={user_id} connectionId={connection_id}")
    else:
        print(f"messaging websocket disconnect lookup-miss connectionId={connection_id}")

    return {
        "statusCode": 200,
        "body": "Disconnected",
    }
