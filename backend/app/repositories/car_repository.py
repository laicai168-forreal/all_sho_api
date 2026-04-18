# app/repositories/car_repository.py

import json
import uuid

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
