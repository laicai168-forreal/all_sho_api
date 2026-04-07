import json
import os
import boto3
import psycopg2

secrets_client = boto3.client("secretsmanager")
SECRET_ARN = os.environ.get("SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
DB_SECRET = None
DB_CONN = None


def get_db_connection():
    global DB_SECRET, DB_CONN

    # Cache secret
    if DB_SECRET is None:
        resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
        DB_SECRET = json.loads(resp["SecretString"])

    # Cache connection
    if DB_CONN is None or DB_CONN.closed:
        DB_CONN = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_SECRET["username"],
            password=DB_SECRET["password"],
            host=DB_SECRET["host"],
            port=int(DB_SECRET.get("port", 5432)),
        )

    return DB_CONN


def handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}

        item_id = params.get("itemId")
        car_id = params.get("carId")
        delete_all = params.get("deleteAll") == "true"
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
            DELETE FROM user_collection_storage
            WHERE user_id = %s
              AND car_id = %s
            RETURNING user_id, car_id;
            """
            cur.execute(sql, (user_id, car_id))
            row = cur.fetchone()
            conn.commit()

        with conn.cursor() as cur:

            if item_id:
                sql = """
                DELETE FROM user_collection_items
                WHERE id = %s AND user_id = %s
                RETURNING id;
                """
                cur.execute(sql, (item_id, user_id))

            elif delete_all and car_id:
                sql = """
                DELETE FROM user_collection_items
                WHERE car_id = %s AND user_id = %s
                RETURNING id;
                """
                cur.execute(sql, (car_id, user_id))

            rows = cur.fetchall()
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
                    "message": "Item removed from inventory successfully",
                    "deleted": row is not None,
                    "userId": user_id,
                    "carId": car_id,
                    "deletedCount": len(rows),
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
