import os
import json
import psycopg2
import psycopg2.extras
import boto3
import uuid
import traceback

secrets_client = boto3.client("secretsmanager")

SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_NAME = os.environ["DB_NAME"]

cors_headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type": "application/json",
}


def parse_bool(value):
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


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


# -----------------------------
# SQL: shared stats CTE
# (better for scaling vs repeating subqueries)
# -----------------------------
STATS_CTE = """
WITH car_stats AS (
  SELECT
    car_id,
    COUNT(DISTINCT user_id) AS owners_count
  FROM user_collection_items
  GROUP BY car_id
),
like_stats AS (
  SELECT
    car_id,
    COUNT(*) AS likes_count
  FROM user_liked_items
  GROUP BY car_id
)
"""


# ---------------------------------------------------
# SQL: single car
# ---------------------------------------------------
def fetch_car_detail(cur, car_id, user_id=None):
    user_join = ""
    params = []

    if user_id:
        own_expr = """
        EXISTS (
          SELECT 1
          FROM user_collection_items uci
          WHERE uci.car_id = c.id AND uci.user_id = %s
        )
        """
        params.append(user_id)
    else:
        own_expr = "false"

    if user_id:
        liked_expr = "(uli.user_id IS NOT NULL)"
        user_join = """
        LEFT JOIN user_liked_items uli
          ON uli.car_id = c.id AND uli.user_id = %s
        """
        params.append(user_id)
    else:
        liked_expr = "false"
        user_join = "LEFT JOIN user_liked_items uli ON false"

    sql = f"""
    {STATS_CTE}
    SELECT
        c.id,
        c.original_id,
        c.title,
        b.name AS brand,
        m.name AS make,
        c.make_ai,
        pl.name AS product_line,
        c.model_ai,
        c.scale,
        c.release_date_ai,
        c.release_date_approximate,
        c.source_url,
        c.crawled_date,
        c.image_url,
        c.images,
        c.additional_info,

        {own_expr} AS own,
        {liked_expr} AS liked,

        COALESCE(cs.owners_count, 0) AS owners_count,
        COALESCE(ls.likes_count, 0) AS likes_count

    FROM cars c

    LEFT JOIN brands b ON b.id = c.brand_id
    LEFT JOIN makes m ON m.id = c.make_id
    LEFT JOIN product_lines pl ON pl.id = c.product_line_id

    {user_join}

    LEFT JOIN car_stats cs ON cs.car_id = c.id
    LEFT JOIN like_stats ls ON ls.car_id = c.id

    WHERE c.id = %s
    """

    params.append(car_id)
    cur.execute(sql, params)
    item = cur.fetchone()
    if item:
        item["owners_preview"] = fetch_car_owners(cur, car_id, limit=5, offset=0)["items"]
    return item


def fetch_car_owners(cur, car_id, limit=20, offset=0):
    sql = """
    WITH owner_rows AS (
        SELECT
            u.id,
            u.username,
            u.profile_image_url,
            MAX(uci.created_at) AS latest_owned_at
        FROM user_collection_items uci
        JOIN users u ON u.id = uci.user_id
        WHERE uci.car_id = %s
        GROUP BY u.id, u.username, u.profile_image_url
    )
    SELECT
        id,
        username,
        profile_image_url,
        latest_owned_at,
        COUNT(*) OVER() AS total_count
    FROM owner_rows
    ORDER BY latest_owned_at DESC NULLS LAST, username ASC
    LIMIT %s OFFSET %s
    """

    cur.execute(sql, (car_id, limit, offset))
    rows = cur.fetchall()
    total = rows[0]["total_count"] if rows else 0

    items = [
        {
            "id": row["id"],
            "username": row["username"],
            "profile_image_url": row["profile_image_url"],
            "latest_owned_at": row["latest_owned_at"],
        }
        for row in rows
    ]

    return {
        "items": items,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------
# SQL: car list
# ---------------------------------------------------
def fetch_car_list(cur, filters, params, user_id, limit, offset, order_clause):
    join_params = []

    # ----- ownership -----
    if user_id:
        own_expr = """
        EXISTS (
          SELECT 1
          FROM user_collection_items uci
          WHERE uci.car_id = c.id AND uci.user_id = %s
        )
        """
        join_params.append(user_id)
    else:
        own_expr = "false"
    # ----- liked -----
    if user_id:
        liked_expr = "(uli.user_id IS NOT NULL)"
        user_join = """
        LEFT JOIN user_liked_items uli
          ON uli.car_id = c.id AND uli.user_id = %s
        """
        join_params.append(user_id)
    else:
        liked_expr = "false"
        user_join = "LEFT JOIN user_liked_items uli ON false"

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
    {STATS_CTE}
    SELECT
      c.id,
      c.title,
      b.name AS brand,
      m.name AS make,
      c.make_ai,
      pl.name AS product_line,
      c.model_ai,
      c.scale,
      c.release_date_ai,
      c.release_date_approximate,
      c.source_url,
      c.crawled_date,
      c.images,

      {own_expr} AS own,
      {liked_expr} AS liked,

      COALESCE(cs.owners_count, 0) AS owners_count,
      COALESCE(ls.likes_count, 0) AS likes_count

    FROM cars c

    LEFT JOIN brands b ON b.id = c.brand_id
    LEFT JOIN makes m ON m.id = c.make_id
    LEFT JOIN product_lines pl ON pl.id = c.product_line_id

    {user_join}

    LEFT JOIN car_stats cs ON cs.car_id = c.id
    LEFT JOIN like_stats ls ON ls.car_id = c.id

    {where_clause}
    {order_clause}
    LIMIT %s OFFSET %s
    """

    cur.execute(sql, join_params + params + [limit, offset])
    return cur.fetchall()


# ---------------------------------------------------
# SQL: brands
# ---------------------------------------------------
def fetch_brands(cur):
    cur.execute(
        """
        SELECT id, name
        FROM brands
        ORDER BY name
    """
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
        owners_only = parse_bool(params.get("ownersOnly"))

        limit = int(params.get("limit", 20))
        offset = int(params.get("offset", 0))

        conn = get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if owners_only:
                if not cid:
                    return {
                        "statusCode": 400,
                        "headers": cors_headers,
                        "body": json.dumps({"message": "cid is required for owners lookup"}),
                    }

                owners = fetch_car_owners(cur, cid, limit=limit, offset=offset)
                return {
                    "statusCode": 200,
                    "headers": cors_headers,
                    "body": json.dumps(owners, default=str),
                }

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

            if params.get("bid"):
                filters.append("b.id = %s")
                values.append(params["bid"])

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

            count_sql = f"""
                SELECT COUNT(*)
                FROM cars c
                LEFT JOIN brands b ON b.id = c.brand_id
                {'WHERE ' + ' AND '.join(filters) if filters else ''}
            """

            cur.execute(count_sql, values)
            total = cur.fetchone()["count"]

            brands = fetch_brands(cur)

        conn.close()

        return {
            "statusCode": 200,
            "headers": cors_headers,
            "body": json.dumps(
                {
                    "items": items,
                    "total": total,
                    "brands": brands,
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
            "body": json.dumps({
                "error": str(e),
                "stack": traceback.format_exc()
            }),
        }
