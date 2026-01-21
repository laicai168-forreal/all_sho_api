import os
import json
import psycopg2
import psycopg2.extras
import boto3
import uuid

secrets_client = boto3.client("secretsmanager")

SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_NAME = os.environ["DB_NAME"]

cors_headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type": "application/json",
}


def get_conn():
    secret = json.loads(
        secrets_client.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
    )
    return psycopg2.connect(
        dbname=DB_NAME,
        user=secret["username"],
        password=secret["password"],
        host=secret["host"],
        port=int(secret.get("port", 5432)),
    )


def parse_uuid(value, name):
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"Invalid {name}: {value}")


# ---------------------------------------------------
# SQL: single car
# ---------------------------------------------------
def fetch_car_detail(cur, car_id, user_id=None):
    user_join = ""
    params = []

    if user_id:
        user_join = """
        LEFT JOIN user_collection_storage ucs
          ON ucs.car_id = c.id AND ucs.user_id = %s
        LEFT JOIN user_liked_items uli
          ON uli.car_id = c.id AND uli.user_id = %s
        """
        params.extend([user_id, user_id])
    else:
        user_join = """
        LEFT JOIN user_collection_storage ucs ON false
        LEFT JOIN user_liked_items uli ON false
        """

    sql = f"""
    SELECT
      c.id,
      c.original_id,
      c.title,
      c.brand,
      c.make,
      c.scale,
      c.release_date_ai,
      c.crawled_date,
      c.image_url,
      c.images,
      c.additional_info,

      (ucs.user_id IS NOT NULL) AS own,
      (uli.user_id IS NOT NULL) AS liked,

      COALESCE(oc.owners_count, 0) AS owners_count,
      COALESCE(lc.likes_count, 0) AS likes_count

    FROM cars c

    {user_join}

    LEFT JOIN (
      SELECT car_id, COUNT(*) AS owners_count
      FROM user_collection_storage
      GROUP BY car_id
    ) oc ON oc.car_id = c.id

    LEFT JOIN (
      SELECT car_id, COUNT(*) AS likes_count
      FROM user_liked_items
      GROUP BY car_id
    ) lc ON lc.car_id = c.id

    WHERE c.id = %s
    """

    params.append(car_id)
    cur.execute(sql, params)
    return cur.fetchone()


# ---------------------------------------------------
# SQL: car list
# ---------------------------------------------------
def fetch_car_list(cur, filters, params, user_id, limit, offset, order_clause):
    user_join = ""
    join_params = []

    if user_id:
        user_join = """
        LEFT JOIN user_collection_storage ucs
          ON ucs.car_id = c.id AND ucs.user_id = %s
        LEFT JOIN user_liked_items uli
          ON uli.car_id = c.id AND uli.user_id = %s
        """
        join_params = [user_id, user_id]
    else:
        user_join = """
        LEFT JOIN user_collection_storage ucs ON false
        LEFT JOIN user_liked_items uli ON false
        """

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
    SELECT
      c.id,
      c.title,
      c.brand,
      c.make,
      c.scale,
      c.release_date_ai,
      c.crawled_date,
      c.images,

      (ucs.user_id IS NOT NULL) AS own,
      (uli.user_id IS NOT NULL) AS liked,

      COALESCE(oc.owners_count, 0) AS owners_count,
      COALESCE(lc.likes_count, 0) AS likes_count

    FROM cars c
    {user_join}

    LEFT JOIN (
      SELECT car_id, COUNT(*) AS owners_count
      FROM user_collection_storage
      GROUP BY car_id
    ) oc ON oc.car_id = c.id

    LEFT JOIN (
      SELECT car_id, COUNT(*) AS likes_count
      FROM user_liked_items
      GROUP BY car_id
    ) lc ON lc.car_id = c.id

    {where_clause}
    {order_clause}
    LIMIT %s OFFSET %s
    """

    cur.execute(
        sql,
        join_params + params + [limit, offset],
    )
    return cur.fetchall()


# ---------------------------------------------------
# Lambda handler
# ---------------------------------------------------
def handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}

        user_id = parse_uuid(params.get("userId"), "userId")
        cid = parse_uuid(params.get("cid"), "cid")

        limit = int(params.get("limit", 20))
        offset = int(params.get("offset", 0))

        conn = get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ---- Single car
            if cid:
                item = fetch_car_detail(cur, cid, user_id)
                return {
                    "statusCode": 200,
                    "headers": cors_headers,
                    "body": json.dumps(item, default=str),
                }

            # ---- List
            filters = []
            values = []

            if params.get("brand"):
                filters.append("c.brand = %s")
                values.append(params["brand"])

            if params.get("keyword"):
                filters.append("c.search_vector @@ plainto_tsquery(%s)")
                values.append(params["keyword"])

            order_clause = "ORDER BY c.crawled_date DESC"

            items = fetch_car_list(
                cur,
                filters,
                values,
                user_id,
                limit,
                offset,
                order_clause,
            )

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM cars c
                {'WHERE ' + ' AND '.join(filters) if filters else ''}
                """,
                values,
                )
            total = cur.fetchone()["count"]

        conn.close()

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
        print("ERROR:", e)
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": json.dumps({"error": str(e)}),
        }
