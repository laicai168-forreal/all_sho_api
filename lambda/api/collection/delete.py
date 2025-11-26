import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

def handler(event, context):
    try:
        user_id = event["queryStringParameters"]["userId"]
        body = json.loads(event.get("body", "{}"))
        carId = body.get("carId")

        if not carId:
            return {
                "statusCode": 400,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "Missing 'carId' in body"}),
            }

        pk = f"USER#{user_id}"
        sort_key = f"CAR#{carId}"

        table.delete_item(
            Key={"pk": pk, "sk": sort_key}
        )

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Deleted successfully"}),
        }

    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }
