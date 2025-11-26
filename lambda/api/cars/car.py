import os
import json
import boto3
import base64
import psycopg2
import psycopg2.extras
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")

car_table = dynamodb.Table(os.environ["CAR_TABLE_NAME"])
user_collection_table = dynamodb.Table(os.environ["USER_COLLECTION_TABLE_NAME"])
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")


cors_headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type": "application/json",
}


def get_conn():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret = json.loads(resp["SecretString"])
    creds = {
        "host": secret.get("host"),
        "username": secret.get("username"),
        "password": secret.get("password"),
        "port": int(secret.get("port", 5432)),
    }
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=creds["username"],
        password=creds["password"],
        host=creds["host"],
        port=creds["port"],
    )

    return conn


def handler(event, context):

    print("Received event:", event)
    params = event.get("queryStringParameters") or {}
    brand = params.get("brand")
    keyword = params.get("keyword")
    user_id = params.get("userId")
    limit = int(params.get("limit", 20))
    year = params.get("year")
    offset = int(params.get("offset", 0))
    cid = params.get("cid")

    pk = f"USER#{user_id}"

    # If there is a single cid which is the car id, then get the detailed car info
    if cid:
        data_query = f"""
            SELECT id, original_id, title, brand, make, model_ai, scale, release_date_ai, crawled_date, image_url, images, additional_info, description_ai, make_ai
            FROM cars
            WHERE id = '{cid}'
        """
        sk = f"CAR#{cid}"

        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(data_query)
                items = cur.fetchall()

            uc_response = user_collection_table.query(
                KeyConditionExpression="pk = :pk AND sk = :sk",
                ExpressionAttributeValues={":pk": pk, ":sk": sk},
            )

            user_collections = uc_response.get("Items", [])
            owned_cars = dict()

            if len(user_collections) > 0:
                for t in items:
                    t["own"] = True
                    t["carCollectionSK"] = owned_cars[t["id"]]["sk"]

            return {
                "statusCode": 200,
                "headers": cors_headers,
                "body": json.dumps(
                    items,
                    default=str,
                ),
            }

        except Exception as e:
            return {
                "statusCode": 500,
                "headers": cors_headers,
                "body": json.dumps({"error": str(e)}),
            }
    # If there is no cid, then it will query the car list based on the filters
    else:
        filters = []
        values = []
        if brand:
            filters.append("brand = %s")
            values.append(brand)
        # Filter by year (if your release_date is a DATE or TIMESTAMP)
        if year:
            filters.append("EXTRACT(YEAR FROM release_date) = %s")
            values.append(int(year))

        # Keyword search using full-text search
        if keyword:
            filters.append("search_vector @@ plainto_tsquery('english', %s)")
            values.append(keyword)

        filter_clause = ""

        if filters:
            filter_clause += " WHERE " + " AND ".join(filters)

        pagination_clause = " ORDER BY crawled_date DESC LIMIT %s OFFSET %s"
        pagination_values = values + [limit, offset]

        data_query = f"""
            SELECT id, original_id, title, brand, make, scale, release_date_ai, crawled_date, image_url, images, additional_info
            FROM cars
            {filter_clause}
            {pagination_clause}
        """

        count_query = f"""
            SELECT COUNT(*) AS total
            FROM cars
            {filter_clause}
        """

        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(count_query, values)
                total = cur.fetchone()["total"]

                cur.execute(data_query, pagination_values)
                items = cur.fetchall()

            uc_response = user_collection_table.query(
                KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": pk}
            )

            user_collections = uc_response.get("Items", [])
            owned_cars = dict()

            if user_collections:
                for uc in user_collections:
                    if uc["carId"]:
                        owned_cars[uc["carId"]] = uc

            for t in items:
                if t["id"] in owned_cars:
                    t["own"] = True
                    t["carCollectionSK"] = owned_cars[t["id"]]["sk"]

            return {
                "statusCode": 200,
                "headers": cors_headers,
                "body": json.dumps(
                    {
                        "items": items,
                        "total": total,
                        "pages": (total + limit - 1) // limit,
                    },
                    default=str,
                ),
            }

        except Exception as e:
            return {
                "statusCode": 500,
                "headers": cors_headers,
                "body": json.dumps({"error": str(e)}),
            }
