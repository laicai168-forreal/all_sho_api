import json
import os
import boto3
import psycopg2

secrets_client = boto3.client("secretsmanager")
SECRET_ARN = os.environ.get("SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")


def get_db_connection():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret = json.loads(resp["SecretString"])

    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=secret.get("username"),
        password=secret.get("password"),
        host=secret.get("host"),
        port=int(secret.get("port", 5432)),
    )

    return conn


def handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}

        car_id = params.get("carId")
        if not car_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "carId is required"}),
            }

        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        user_id = claims["sub"]

        if not user_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "userId is required"}),
            }

        conn = get_db_connection()

        with conn.cursor() as cur:
            sql = """
            DELETE FROM user_liked_items
            WHERE user_id = %s
              AND car_id = %s
            RETURNING user_id, car_id;
            """
            cur.execute(sql, (user_id, car_id))
            row = cur.fetchone()
            conn.commit()

        conn.close()

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Authorization,Content-Type",
                "Access-Control-Allow-Methods": "GET,POST,DELETE",
            },
            "body": json.dumps(
                {
                    "message": "Item removed from likes successfully",
                    "deleted": row is not None,
                    "userId": user_id,
                    "carId": car_id,
                }
            ),
        }

    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }
