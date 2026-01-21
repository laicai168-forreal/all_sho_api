import json
import os
import boto3
from helper.utils import DecimalEncoder

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])


def handler(event, context):
    try:
        user_id = event["queryStringParameters"]["userId"]
        # car_id = event["queryStringParameters"]["carId"]
        # brand = event["queryStringParameters"]["brand"]
        pk = f"USER#{user_id}"

        resp = table.query(
            KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": pk}
        )

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps(resp.get("Items", []), cls=DecimalEncoder),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }
