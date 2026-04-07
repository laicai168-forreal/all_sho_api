import json
import os
import boto3
import psycopg2
import traceback

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


def success_response(data=None, message="Success"):
    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE",
        },
        "body": json.dumps({"message": message, "data": data}),
    }


def error_response(message="Error", status_code=400):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({"error": message}),
    }

def resolve_storage_location(cur, item, user_id):
    storage_location = item.get("storageLocation") or {}

    storage_location_id = storage_location.get("id")
    storage_location_name = storage_location.get("name")

    if not storage_location_id and storage_location_name:
        cur.execute("""
            INSERT INTO storage_locations (user_id, name)
            VALUES (%s, %s)
            ON CONFLICT (user_id, LOWER(name))
            DO UPDATE SET name = EXCLUDED.name
            RETURNING id;
        """, (user_id, storage_location_name))

        storage_location_id = cur.fetchone()[0]
    return storage_location_id


def handler(event, context):
    try:
        if "body" in event and isinstance(event["body"], str):
            body = json.loads(event["body"])
        else:
            body = event

        items = body.get("items", [])
        created_ids = []
        updated_ids = []

        if not items:
            return error_response("items array required")

        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        user_id = claims["sub"]

        if not user_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "userId is required"}),
            }

        conn = get_db_connection()
        conn.autocommit = False

        try:
            with conn.cursor() as cur:
                for item in items:
                    item_id = item.get("itemId")

                    if not item_id:
                        storage_location_id = resolve_storage_location(
                            cur, item, user_id
                        )

                        sql = """
                        INSERT INTO user_collection_items
                        (user_id, car_id, condition, purchase_price, purchased_at,
                        photos, attributes, count, notes, is_published, storage_location_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, car_id;
                        """

                        cur.execute(sql, (
                            user_id,
                            item.get("carId"),
                            item.get("condition", "UNKNOWN"),
                            item.get("purchasePrice"),
                            item.get("purchasedAt"),
                            json.dumps(item.get("photos", [])),
                            json.dumps(item.get("attributes", {})),
                            item.get("count", 1),
                            item.get("notes"),
                            item.get("isPublished", False),
                            storage_location_id
                        ))

                        created = cur.fetchone()

                        created_ids.append(
                            {"id": created[0], "carId": created[1]}
                        )

                    else:
                        storage_location_id = resolve_storage_location(
                            cur, item, user_id
                        )

                        sql = """
                        UPDATE user_collection_items
                        SET
                            condition = %s,
                            purchase_price = %s,
                            purchased_at = %s,
                            photos = %s,
                            attributes = %s,
                            count = %s,
                            notes = %s,
                            is_published = %s,
                            storage_location_id = %s,
                            updated_at = now()
                        WHERE id = %s
                        AND user_id = %s
                        RETURNING id, car_id;
                        """

                        cur.execute(sql, (
                            item.get("condition"),
                            item.get("purchasePrice"),
                            item.get("purchasedAt"),
                            json.dumps(item.get("photos", [])),
                            json.dumps(item.get("attributes", {})),
                            item.get("count", 1),
                            item.get("notes"),
                            item.get("isPublished", False),
                            storage_location_id,
                            item_id,
                            user_id
                        ))

                        updated = cur.fetchone()

                        if not updated:
                            conn.rollback()
                            return error_response("Item not found")

                        updated_ids.append({"id": updated[0], "carId": updated[1]})

                conn.commit()
                return success_response(
                    {"created": created_ids, "updated": updated_ids}
                )

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }),
        }
