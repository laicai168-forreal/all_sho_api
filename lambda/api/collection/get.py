import json
import os
import math
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

        page = int(params.get("page", 1))
        page_size = int(params.get("pageSize", 20))
        order = params.get("order", "desc").lower()
        keyword = params.get("q")
        car_id = params.get("carId")
        meta_data_param = params.get("metadata")

        meta_data = meta_data_param is not None and meta_data_param.lower() == "true"

        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        user_id = claims.get("sub")

        if not user_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "userId is required"}),
            }

        conn = get_db_connection()

        with conn.cursor() as cur:
            if meta_data:
                conditions_sql = """
                SELECT enumlabel
                FROM pg_enum
                WHERE enumtypid = 'collection_condition'::regtype
                ORDER BY enumsortorder;
                """

                cur.execute(conditions_sql)
                condition_rows = cur.fetchall()

                condition_types = [row[0] for row in condition_rows]

                locations_sql = """
                SELECT id, name
                FROM storage_locations
                WHERE user_id = %s
                ORDER BY name;
                """

                cur.execute(locations_sql, (user_id,))
                rows = cur.fetchall()

                locations = [
                    {
                        "id": row[0],
                        "name": row[1]
                    }
                    for row in rows
                ]

                return {
                    "statusCode": 200,
                    "headers": {"Access-Control-Allow-Origin": "*"},
                    "body": json.dumps(
                        {
                            "totalLocations": len(locations),
                            "locations": locations,
                            "conditionTypes": condition_types,
                        }
                    ),
                }
            elif car_id:
                car_sql = """
                SELECT id, title, brand, original_id, images, brand_id
                FROM cars
                WHERE id = %s
                LIMIT 1;
                """

                cur.execute(car_sql, (car_id,))
                car_row = cur.fetchone()

                if not car_row:
                    return {
                        "statusCode": 404,
                        "body": json.dumps({"message": "Car not found"})
                    }

                car = {
                    "id": car_row[0],
                    "title": car_row[1],
                    "brand": car_row[2],
                    "originalId": car_row[3],
                    "images": car_row[4],
                }

                car_brand_id = car_row[5]

                items_sql = """
                SELECT
                    uci.id,
                    uci.condition,
                    uci.purchase_price,
                    uci.purchased_at,
                    uci.photos,
                    uci.created_at,
                    uci.attributes,
                    uci.count,
                    uci.updated_at,
                    uci.is_published,
                    uci.notes,
                    uci.car_id,
                    sl.id,
                    sl.name
                FROM user_collection_items uci
                LEFT JOIN storage_locations sl
                ON sl.id = uci.storage_location_id
                WHERE uci.user_id = %s
                AND uci.car_id = %s
                ORDER BY uci.created_at DESC;
                """

                cur.execute(items_sql, (user_id, car_id))
                rows = cur.fetchall()

                packaging_sql = """
                SELECT id, key, label
                FROM brand_packaging_types
                WHERE brand_id = %s
                ORDER BY label;
                """

                cur.execute(packaging_sql, (car_brand_id,))
                packaging_rows = cur.fetchall()

                packaging_types = [
                    {
                        "id": row[0],
                        "key": row[1],
                        "label": row[2]
                    }
                    for row in packaging_rows
                ]

                items = [
                    {
                        "itemId": row[0],
                        "condition": row[1],
                        "purchasePrice": float(row[2]) if row[2] else None,
                        "purchasedAt": row[3].isoformat() if row[3] else None,
                        "photos": row[4],
                        "createdAt": row[5].isoformat() if row[5] else None,
                        "attributes": row[6],
                        "count": row[7],
                        "updatedAt": row[8].isoformat() if row[8] else None,
                        "isPublished": row[9],
                        "notes": row[10],
                        "carId": row[11],
                        "storageLocation": (
                            {"id": row[12], "name": row[13]} if row[12] else None
                        ),
                    }
                    for row in rows
                ]

                return {
                    "statusCode": 200,
                    "headers": {"Access-Control-Allow-Origin": "*"},
                    "body": json.dumps(
                        {
                            "car": car,
                            "totalItems": len(items),
                            "packagingTypes": packaging_types,
                            "items": items,
                        }
                    ),
                }

            else:
                if page < 1:
                    page = 1
                if page_size > 50:
                    page_size = 50
                if order not in ("asc", "desc"):
                    order = "desc"

                offset = (page - 1) * page_size
                order_clause = "ASC" if order == "asc" else "DESC"
                # 1️⃣ total count
                count_sql = """
                SELECT COUNT(DISTINCT uci.car_id)
                FROM user_collection_items uci
                JOIN cars c ON c.id = uci.car_id
                WHERE uci.user_id = %s
                AND (
                    %s IS NULL
                    OR c.search_vector @@ websearch_to_tsquery('simple', %s)
                );
                """
                cur.execute(count_sql, (user_id, keyword, keyword))
                total_items = cur.fetchone()[0]

                # 2️⃣ paginated data
                data_sql = f"""
                SELECT
                    c.id,
                    c.title,
                    c.brand,
                    c.original_id,
                    c.images,
                    SUM(uci.count) AS total_count,
                    COUNT(uci.id) AS batch_count,
                    MAX(uci.created_at) AS latest_added
                FROM user_collection_items uci
                JOIN cars c ON c.id = uci.car_id
                WHERE uci.user_id = %s
                AND (
                    %s IS NULL
                    OR c.search_vector @@ websearch_to_tsquery('simple', %s)
                )
                GROUP BY c.id, c.title, c.brand, c.original_id, c.images
                ORDER BY latest_added {order_clause}
                LIMIT %s OFFSET %s;
                """

                cur.execute(
                    data_sql,
                    (user_id, keyword, keyword, page_size, offset),
                )

                rows = cur.fetchall()

            conn.close()

            total_pages = math.ceil(total_items / page_size) if page_size else 0

            items = [
                {
                    "carId": row[0],
                    "title": row[1],
                    "brand": row[2],
                    "originalId": row[3],
                    "images": row[4],
                    "totalCount": row[5],
                    "batchCount": row[6],
                    "latestAdded": row[7].isoformat(),
                }
                for row in rows
            ]

            return {
                "statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps(
                    {
                        "page": page,
                        "pageSize": page_size,
                        "totalItems": total_items,
                        "totalPages": total_pages,
                        "order": order,
                        "query": keyword,
                        "items": items,
                    }
                ),
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }
