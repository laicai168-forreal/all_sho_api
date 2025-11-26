import json
import os
import time
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

def handler(event, context):
    try:
        body = json.loads(event["body"])
        # user_id = event['pathParameters'].get('userId')
        user_id = body["userId"]
        car_id = body["carId"]

        timestamp = int(time.time())
        pk = f"USER#{user_id}"
        sk = f"CAR#{car_id}"

        # Also write GSI attributes
        item = {
            "pk": pk,
            "sk": sk,
            "carId": car_id,
            "userId": user_id,
            "createdAt": timestamp,
            "gsi1pk": f"CAR#{car_id}",
            "gsi1sk": f"USER#{user_id}#{timestamp}",
        }

        table.put_item(Item=item)

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Added to collection", "item": item}),
        }

    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }