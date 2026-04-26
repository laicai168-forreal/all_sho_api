# app/repositories/car_repository.py

import json
import uuid
import re

from psycopg2.extras import Json, RealDictCursor

from app.common.db import get_db_connection


ALLOWED_CAR_FIELDS = {
    "code": "code",
    "brand_id": "brand_id",
    "product_line_id": "product_line_id",
    "make_id": "make_id",
    "parent_id": "parent_id",
    "brand": "brand",
    "make": "make",
    "scale": "scale",
    "image_url": "image_url",
    "additional_info": "additional_info",
    "title": "title",
    "images": "images",
    "original_id": "original_id",
    "release_date_approximate": "release_date_approximate",
    "description_ai": "description_ai",
    "make_ai": "make_ai",
    "model_ai": "model_ai",
    "source_url": "source_url",
    "is_chase": "is_chase",
    "is_limited": "is_limited",
    "limited_pieces": "limited_pieces",
}

JSONB_FIELDS = {"additional_info", "images"}
# Shared aggregate CTE for public car reads so list/detail stay consistent on
# owners_count and likes_count without duplicating the counting logic.
CAR_STATS_CTE = """
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


def _sanitize_car_payload(payload):
    sanitized = {}

    for key, db_key in ALLOWED_CAR_FIELDS.items():
        if key in payload:
            value = payload[key]
            if db_key in JSONB_FIELDS and value is not None:
                sanitized[db_key] = Json(value)
            else:
                sanitized[db_key] = value

    return sanitized


def _build_insert_parts(payload):
    columns = []
    values = []
    placeholders = []

    for column, value in payload.items():
        columns.append(column)
        values.append(value)
        placeholders.append("%s")

    return columns, values, placeholders


def _build_update_parts(payload):
    assignments = []
    values = []

    for column, value in payload.items():
        assignments.append(f"{column} = %s")
        values.append(value)

    return assignments, values


def create_car(payload, actor_user_id):
    conn = get_db_connection()
    normalized = _sanitize_car_payload(payload)

    if not normalized.get("code"):
        raise ValueError("code is required")
    if not normalized.get("brand"):
        raise ValueError("brand is required")

    normalized["created_by"] = actor_user_id
    normalized["updated_by"] = actor_user_id

    columns, values, placeholders = _build_insert_parts(normalized)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            INSERT INTO cars ({", ".join(columns)})
            VALUES ({", ".join(placeholders)})
            RETURNING id
            """,
            values,
        )
        created = cur.fetchone()

    return get_car_by_id(created["id"])


def update_car(car_id, payload, actor_user_id):
    conn = get_db_connection()
    normalized = _sanitize_car_payload(payload)

    if not normalized:
        raise ValueError("No updatable fields provided")

    normalized["updated_by"] = actor_user_id
    assignments, values = _build_update_parts(normalized)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            UPDATE cars
            SET {", ".join(assignments)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            values + [car_id],
        )
        updated = cur.fetchone()

    if not updated:
        return None

    return get_car_by_id(updated["id"])


def delete_car(car_id):
    conn = get_db_connection()

    with conn.cursor() as cur:
        cur.execute("DELETE FROM cars WHERE id = %s", (car_id,))
        return cur.rowcount


def get_car_by_id(car_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                c.*,
                b.name AS brand_name,
                m.name AS make_name,
                pl.name AS product_line_name
            FROM cars c
            LEFT JOIN brands b ON b.id = c.brand_id
            LEFT JOIN makes m ON m.id = c.make_id
            LEFT JOIN product_lines pl ON pl.id = c.product_line_id
            WHERE c.id = %s
            """,
            (car_id,),
        )
        return cur.fetchone()


def get_car_by_brand_and_original_id(brand, original_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM cars
            WHERE LOWER(brand) = LOWER(%s)
              AND original_id = %s
            LIMIT 1
            """,
            (brand, original_id),
        )
        return cur.fetchone()


def car_image_is_used_elsewhere(car_id, image_url):
    conn = get_db_connection()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM cars c
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(c.images) = 'array' THEN c.images
                        ELSE '[]'::jsonb
                    END
                ) AS image
                WHERE c.id <> %s
                  AND (
                    image->>'s3_url' = %s
                    OR image->>'original_url' = %s
                  )
            )
            """,
            (car_id, image_url, image_url),
        )
        row = cur.fetchone()
        return bool(row and row[0])


def get_public_car_detail(car_id, user_id=None):
    # Mirrors the legacy public car-detail response shape, including optional
    # own/liked flags and a small owners preview for the car detail page.
    conn = get_db_connection()
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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            {CAR_STATS_CTE}
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
            """,
            params + [car_id],
        )
        item = cur.fetchone()
        if item:
            item["owners_preview"] = list_car_owners(car_id, limit=5, offset=0)["items"]
        return item


def list_public_cars(filters=None, values=None, user_id=None, limit=20, offset=0):
    # Public car list query used by the main cars page and admin maintenance
    # list. Keep this shape aligned with the previous Lambda response so the
    # frontend migration stays low-risk.
    conn = get_db_connection()
    filters = filters or []
    values = values or []
    join_params = []

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            {CAR_STATS_CTE}
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
            ORDER BY c.crawled_date DESC
            LIMIT %s OFFSET %s
            """,
            join_params + values + [limit, offset],
        )
        items = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM cars c
            LEFT JOIN brands b ON b.id = c.brand_id
            {where_clause}
            """,
            values,
        )
        total = cur.fetchone()["count"]

    return {
        "items": items,
        "total": total,
        "pages": (total + limit - 1) // limit,
    }


def list_car_owners(car_id, limit=20, offset=0):
    # Return one row per owner, ordered by their most recent add date for this
    # car. The window count lets the UI paginate without a second count query.
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
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
            """,
            (car_id, limit, offset),
        )
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


def list_brands():
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name
            FROM brands
            ORDER BY name
            """
        )
        return cur.fetchall()


def list_makes():
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name
            FROM makes
            ORDER BY name
            """
        )
        return cur.fetchall()


def list_product_lines():
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, brand_id
            FROM product_lines
            ORDER BY name
            """
        )
        return cur.fetchall()


def get_brand_by_id(brand_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM brands WHERE id = %s", (brand_id,))
        return cur.fetchone()


def get_make_by_id(make_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM makes WHERE id = %s", (make_id,))
        return cur.fetchone()


def get_product_line_by_id(product_line_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, brand_id FROM product_lines WHERE id = %s",
            (product_line_id,),
        )
        return cur.fetchone()


def get_brand_by_name(name):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name FROM brands WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (name,),
        )
        return cur.fetchone()


def get_make_by_name(name):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name FROM makes WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (name,),
        )
        return cur.fetchone()


def get_product_line_by_name_and_brand(name, brand_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, brand_id
            FROM product_lines
            WHERE brand_id = %s
              AND LOWER(name) = LOWER(%s)
            LIMIT 1
            """,
            (brand_id, name),
        )
        return cur.fetchone()


def create_brand(name):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO brands (id, name)
            VALUES (gen_random_uuid(), %s)
            RETURNING id, name
            """,
            (name,),
        )
        return cur.fetchone()


def create_make(name):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO makes (id, name)
            VALUES (gen_random_uuid(), %s)
            RETURNING id, name
            """,
            (name,),
        )
        return cur.fetchone()


def create_product_line(name, brand_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO product_lines (id, name, brand_id)
            VALUES (gen_random_uuid(), %s, %s)
            RETURNING id, name, brand_id
            """,
            (name, brand_id),
        )
        return cur.fetchone()


def build_hot_wheels_code(sku):
    slug = re.sub(r"[^a-z0-9]+", "-", (sku or "").strip().lower()).strip("-")
    return f"hotwheels-{slug or uuid.uuid4().hex[:10]}"


def duplicate_car(source_car_id, actor_user_id, overrides=None):
    overrides = overrides or {}
    source = get_car_by_id(source_car_id)
    if not source:
        return None

    payload = {
        "code": overrides.get("code") or f"{source['code']}-copy-{uuid.uuid4().hex[:8]}",
        "brand_id": source.get("brand_id"),
        "product_line_id": source.get("product_line_id"),
        "make_id": source.get("make_id"),
        "parent_id": source.get("parent_id"),
        "brand": overrides.get("brand", source.get("brand")),
        "make": overrides.get("make", source.get("make")),
        "scale": overrides.get("scale", source.get("scale")),
        "image_url": overrides.get("image_url", source.get("image_url")),
        "additional_info": overrides.get("additional_info", source.get("additional_info")),
        "title": overrides.get("title", source.get("title")),
        "images": overrides.get("images", source.get("images")),
        "original_id": overrides.get("original_id"),
        "release_date_approximate": overrides.get(
            "release_date_approximate", source.get("release_date_approximate")
        ),
        "description_ai": overrides.get("description_ai", source.get("description_ai")),
        "make_ai": overrides.get("make_ai", source.get("make_ai")),
        "model_ai": overrides.get("model_ai", source.get("model_ai")),
        "source_url": overrides.get("source_url", source.get("source_url")),
        "is_chase": overrides.get("is_chase", source.get("is_chase")),
        "is_limited": overrides.get("is_limited", source.get("is_limited")),
        "limited_pieces": overrides.get("limited_pieces", source.get("limited_pieces")),
    }

    return create_car(payload, actor_user_id)


def create_change_request(payload, submitted_by):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO car_change_requests (
                car_id,
                submitted_by,
                status,
                request_type,
                payload,
                uploaded_images
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            RETURNING *
            """,
            (
                payload.get("car_id"),
                submitted_by,
                "pending",
                payload["request_type"],
                json.dumps(payload.get("payload", {})),
                json.dumps(payload.get("uploaded_images", [])),
            ),
        )
        return cur.fetchone()


def list_change_requests(status=None, submitted_by=None, limit=20, offset=0):
    conn = get_db_connection()
    filters = []
    values = []

    if status:
        filters.append("ccr.status = %s")
        values.append(status)

    if submitted_by:
        filters.append("ccr.submitted_by = %s")
        values.append(submitted_by)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                ccr.*,
                u.username AS submitted_by_username,
                reviewer.username AS reviewed_by_username,
                c.title AS car_title
            FROM car_change_requests ccr
            LEFT JOIN users u ON u.id = ccr.submitted_by
            LEFT JOIN users reviewer ON reviewer.id = ccr.reviewed_by
            LEFT JOIN cars c ON c.id = ccr.car_id
            {where_clause}
            ORDER BY ccr.created_at DESC
            LIMIT %s OFFSET %s
            """,
            values + [limit, offset],
        )
        return cur.fetchall()


def get_change_request(request_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM car_change_requests
            WHERE id = %s
            """,
            (request_id,),
        )
        return cur.fetchone()


def get_change_request_detail(request_id):
    # Use the joined/detail shape for review screens and customer request pages
    # so usernames and current car context do not require extra list queries.
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                ccr.*,
                u.username AS submitted_by_username,
                reviewer.username AS reviewed_by_username,
                c.title AS car_title
            FROM car_change_requests ccr
            LEFT JOIN users u ON u.id = ccr.submitted_by
            LEFT JOIN users reviewer ON reviewer.id = ccr.reviewed_by
            LEFT JOIN cars c ON c.id = ccr.car_id
            WHERE ccr.id = %s
            """,
            (request_id,),
        )
        return cur.fetchone()


def update_change_request(request_id, payload):
    # This is intentionally a partial update. Missing keys mean "leave the
    # stored request as-is", while present keys can overwrite or clear values.
    conn = get_db_connection()
    assignments = []
    values = []

    if "request_type" in payload:
        assignments.append("request_type = %s")
        values.append(payload["request_type"])

    if "payload" in payload:
        assignments.append("payload = %s::jsonb")
        values.append(json.dumps(payload.get("payload") or {}))

    if "uploaded_images" in payload:
        assignments.append("uploaded_images = %s::jsonb")
        values.append(json.dumps(payload.get("uploaded_images") or []))

    if not assignments:
        return get_change_request_detail(request_id)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            UPDATE car_change_requests
            SET {", ".join(assignments)}
            WHERE id = %s
            RETURNING *
            """,
            values + [request_id],
        )
        updated = cur.fetchone()

    if not updated:
        return None

    return get_change_request_detail(request_id)


def count_weekly_change_requests(submitted_by):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM car_change_requests
            WHERE submitted_by = %s
              AND created_at >= NOW() - INTERVAL '7 days'
            """,
            (submitted_by,),
        )
        row = cur.fetchone()
        return row["count"] if row else 0


def get_weekly_change_request_summary(submitted_by):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS used_count,
                MIN(created_at) AS oldest_in_window
            FROM car_change_requests
            WHERE submitted_by = %s
              AND created_at >= NOW() - INTERVAL '7 days'
            """,
            (submitted_by,),
        )
        return cur.fetchone()


def review_change_request(request_id, status, review_notes, reviewed_by, car_id=None):
    # Store the resolved car_id after approval so new-car suggestions become
    # linked to the created car for later history/detail views.
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE car_change_requests
            SET
                status = %s,
                review_notes = %s,
                reviewed_by = %s,
                reviewed_at = NOW(),
                car_id = COALESCE(%s, car_id)
            WHERE id = %s
            RETURNING *
            """,
            (status, review_notes, reviewed_by, car_id, request_id),
        )
        reviewed = cur.fetchone()

    if not reviewed:
        return None

    return get_change_request_detail(request_id)


def list_hot_wheels_staging(review_status=None, page_type=None, keyword=None, job_id=None, limit=20, offset=0):
    conn = get_db_connection()
    filters = []
    values = []
    has_job_id_column = hot_wheels_staging_has_job_id_column(conn)

    if review_status:
        filters.append("review_status = %s")
        values.append(review_status)

    if page_type:
        filters.append("page_type = %s")
        values.append(page_type)

    if job_id and has_job_id_column:
        filters.append("job_id = %s")
        values.append(job_id)

    if keyword:
        filters.append(
            """
            (
                sku ILIKE %s
                OR title ILIKE %s
                OR page_title ILIKE %s
                OR source_url ILIKE %s
                OR COALESCE(series_name, '') ILIKE %s
                OR COALESCE(section_name, '') ILIKE %s
            )
            """
        )
        pattern = f"%{keyword}%"
        values.extend([pattern, pattern, pattern, pattern, pattern, pattern])

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Window count keeps the admin table paginated without a second count
        # query, which is useful while we are still iterating on parser output.
        cur.execute(
            f"""
            SELECT
                hws.*,
                COUNT(*) OVER() AS total_count
            FROM hot_wheels_fandom_staging hws
            {where_clause}
            ORDER BY hws.updated_at DESC, hws.created_at DESC
            LIMIT %s OFFSET %s
            """,
            values + [limit, offset],
        )
        rows = cur.fetchall()

    total = rows[0]["total_count"] if rows else 0
    items = [{k: v for k, v in row.items() if k != "total_count"} for row in rows]

    return {
        "items": items,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


def get_hot_wheels_staging_item(item_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM hot_wheels_fandom_staging
            WHERE id = %s
            """,
            (item_id,),
        )
        return cur.fetchone()


def list_hot_wheels_staging_items_by_ids(item_ids):
    if not item_ids:
        return []

    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM hot_wheels_fandom_staging
            WHERE id = ANY(%s::uuid[])
            ORDER BY updated_at DESC, created_at DESC
            """,
            (item_ids,),
        )
        return cur.fetchall()


def review_hot_wheels_staging_item(item_id, review_status, review_notes):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE hot_wheels_fandom_staging
            SET
                review_status = %s,
                review_notes = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (review_status, review_notes, item_id),
        )
        reviewed = cur.fetchone()

    return reviewed


def mark_hot_wheels_staging_imported(item_id, imported_car_id, review_notes=None):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE hot_wheels_fandom_staging
            SET
                review_status = 'imported',
                imported_car_id = %s,
                review_notes = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (imported_car_id, review_notes, item_id),
        )
        return cur.fetchone()


def batch_review_hot_wheels_staging_items(item_ids, review_status, review_notes):
    if not item_ids:
        return []

    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE hot_wheels_fandom_staging
            SET
                review_status = %s,
                review_notes = %s,
                updated_at = NOW()
            WHERE id = ANY(%s::uuid[])
            RETURNING *
            """,
            (review_status, review_notes, item_ids),
        )
        return cur.fetchall()


def list_hot_wheels_staging_jobs(limit=20, offset=0):
    conn = get_db_connection()
    if not hot_wheels_staging_has_job_id_column(conn):
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH job_rows AS (
                SELECT
                    job_id,
                    MAX(updated_at) AS latest_updated_at,
                    MIN(created_at) AS first_created_at,
                    COUNT(*) AS row_count,
                    COUNT(*) FILTER (WHERE review_status = 'pending') AS pending_count,
                    COUNT(*) FILTER (WHERE review_status = 'approved') AS approved_count,
                    COUNT(*) FILTER (WHERE review_status = 'rejected') AS rejected_count,
                    COUNT(*) FILTER (WHERE review_status = 'flagged') AS flagged_count
                FROM hot_wheels_fandom_staging
                WHERE job_id IS NOT NULL
                GROUP BY job_id
            )
            SELECT
                job_id,
                latest_updated_at,
                first_created_at,
                row_count,
                pending_count,
                approved_count,
                rejected_count,
                flagged_count,
                COUNT(*) OVER() AS total_count
            FROM job_rows
            ORDER BY latest_updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cur.fetchall()

    total = rows[0]["total_count"] if rows else 0
    items = [{k: v for k, v in row.items() if k != "total_count"} for row in rows]
    return {
        "items": items,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


def hot_wheels_staging_has_job_id_column(conn=None):
    own_conn = conn is None
    conn = conn or get_db_connection()

    try:
        with conn.cursor() as cur:
            # The Hot Wheels staging feature shipped before `job_id` existed.
            # Keep review/list APIs backward-compatible so environments that
            # missed the later migration still load instead of crashing.
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'hot_wheels_fandom_staging'
                      AND column_name = 'job_id'
                )
                """
            )
            row = cur.fetchone()
            return bool(row and row[0])
    finally:
        if own_conn:
            conn.close()
