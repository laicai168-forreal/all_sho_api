import math
from psycopg2.extras import RealDictCursor, Json

from app.common.db import get_db_connection
from app.repositories.car_repository import CAR_STATS_CTE


def _get_or_create_storage_location(cur, user_id, item):
    storage_location = item.get("storageLocation") or {}
    storage_location_id = item.get("storageLocationId") or storage_location.get("id")
    storage_location_name = (
        item.get("storageLocationName")
        or storage_location.get("name")
    )

    if storage_location_id:
        return storage_location_id

    if not storage_location_name:
        return None

    trimmed_name = storage_location_name.strip()
    if not trimmed_name:
        return None

    cur.execute(
        """
        SELECT id
        FROM storage_locations
        WHERE user_id = %s
          AND LOWER(name) = LOWER(%s)
        LIMIT 1
        """,
        (user_id, trimmed_name),
    )
    existing = cur.fetchone()
    if existing:
        return existing["id"]

    cur.execute(
        """
        INSERT INTO storage_locations (user_id, name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (user_id, trimmed_name),
    )
    created = cur.fetchone()
    return created["id"]


def _normalize_collection_condition(condition):
    return condition or "UNKNOWN"


def _normalize_collection_count(count):
    return count if count is not None else 1


def _normalize_collection_published(is_published):
    return bool(is_published) if is_published is not None else False


def list_collection_metadata(user_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT enumlabel
            FROM pg_enum
            WHERE enumtypid = 'collection_condition'::regtype
            ORDER BY enumsortorder
            """
        )
        condition_types = [row["enumlabel"] for row in cur.fetchall()]

        cur.execute(
            """
            SELECT id, name
            FROM storage_locations
            WHERE user_id = %s
            ORDER BY name
            """,
            (user_id,),
        )
        locations = cur.fetchall()

    return {
        "totalLocations": len(locations),
        "locations": locations,
        "conditionTypes": condition_types,
    }


def list_collection_entries(user_id, page=1, page_size=20, order="desc", keyword=None):
    conn = get_db_connection()
    safe_page = max(page or 1, 1)
    safe_page_size = min(max(page_size or 20, 1), 50)
    safe_order = "ASC" if (order or "").lower() == "asc" else "DESC"
    offset = (safe_page - 1) * safe_page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT uci.car_id) AS total_items
            FROM user_collection_items uci
            JOIN cars c ON c.id = uci.car_id
            WHERE uci.user_id = %s
              AND (
                %s IS NULL
                OR c.search_vector @@ websearch_to_tsquery('simple', %s)
              )
            """,
            (user_id, keyword, keyword),
        )
        total_items = int((cur.fetchone() or {}).get("total_items") or 0)

        cur.execute(
            f"""
            SELECT
                c.id AS car_id,
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
            ORDER BY latest_added {safe_order}
            LIMIT %s OFFSET %s
            """,
            (user_id, keyword, keyword, safe_page_size, offset),
        )
        rows = cur.fetchall()

    return {
        "page": safe_page,
        "pageSize": safe_page_size,
        "totalItems": total_items,
        "totalPages": math.ceil(total_items / safe_page_size) if safe_page_size else 0,
        "order": order or "desc",
        "query": keyword,
        "items": [
            {
                "carId": row["car_id"],
                "title": row["title"],
                "brand": row["brand"],
                "originalId": row["original_id"],
                "images": row["images"],
                "totalCount": int(row["total_count"] or 0),
                "batchCount": int(row["batch_count"] or 0),
                "latestAdded": row["latest_added"].isoformat() if row["latest_added"] else None,
            }
            for row in rows
        ],
    }


def list_liked_cars(user_id, page=1, page_size=20, keyword=None):
    conn = get_db_connection()
    safe_page = max(page or 1, 1)
    safe_page_size = min(max(page_size or 20, 1), 50)
    offset = (safe_page - 1) * safe_page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total_items
            FROM user_liked_items uli
            JOIN cars c ON c.id = uli.car_id
            LEFT JOIN brands b ON b.id = c.brand_id
            WHERE uli.user_id = %s
              AND COALESCE(b.is_visible, TRUE) = TRUE
              AND COALESCE(c.is_visible, TRUE) = TRUE
              AND (
                %s IS NULL
                OR c.search_vector @@ websearch_to_tsquery('simple', %s)
              )
            """,
            (user_id, keyword, keyword),
        )
        total_items = int((cur.fetchone() or {}).get("total_items") or 0)

        cur.execute(
            f"""
            {CAR_STATS_CTE}
            SELECT
                c.id,
                c.title,
                c.original_id,
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
                COALESCE(c.is_visible, TRUE) AS is_visible,
                EXISTS (
                  SELECT 1
                  FROM user_collection_items uci
                  WHERE uci.car_id = c.id AND uci.user_id = %s
                ) AS own,
                TRUE AS liked,
                COALESCE(cs.owners_count, 0) AS owners_count,
                COALESCE(ls.likes_count, 0) AS likes_count
            FROM user_liked_items uli
            JOIN cars c ON c.id = uli.car_id
            LEFT JOIN brands b ON b.id = c.brand_id
            LEFT JOIN makes m ON m.id = c.make_id
            LEFT JOIN product_lines pl ON pl.id = c.product_line_id
            LEFT JOIN car_stats cs ON cs.car_id = c.id
            LEFT JOIN like_stats ls ON ls.car_id = c.id
            WHERE uli.user_id = %s
              AND COALESCE(b.is_visible, TRUE) = TRUE
              AND COALESCE(c.is_visible, TRUE) = TRUE
              AND (
                %s IS NULL
                OR c.search_vector @@ websearch_to_tsquery('simple', %s)
              )
            ORDER BY c.crawled_date DESC NULLS LAST, c.id DESC
            LIMIT %s OFFSET %s
            """,
            (
                user_id,
                user_id,
                keyword,
                keyword,
                safe_page_size,
                offset,
            ),
        )
        rows = cur.fetchall()

    return {
        "page": safe_page,
        "pageSize": safe_page_size,
        "totalItems": total_items,
        "totalPages": math.ceil(total_items / safe_page_size) if safe_page_size else 0,
        "query": keyword,
        "items": rows,
    }


def get_collection_by_car_id(user_id, car_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, title, brand, original_id, images, brand_id
            FROM cars
            WHERE id = %s
            LIMIT 1
            """,
            (car_id,),
        )
        car = cur.fetchone()

        if not car:
            return None

        cur.execute(
            """
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
                sl.id AS storage_location_id,
                sl.name AS storage_location_name
            FROM user_collection_items uci
            LEFT JOIN storage_locations sl
              ON sl.id = uci.storage_location_id
            WHERE uci.user_id = %s
              AND uci.car_id = %s
            ORDER BY uci.created_at DESC
            """,
            (user_id, car_id),
        )
        item_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, key, label
            FROM brand_packaging_types
            WHERE brand_id = %s
            ORDER BY label
            """,
            (car["brand_id"],),
        )
        packaging_rows = cur.fetchall()

    return {
        "car": {
            "id": car["id"],
            "title": car["title"],
            "brand": car["brand"],
            "originalId": car["original_id"],
            "images": car["images"],
        },
        "totalItems": len(item_rows),
        "packagingTypes": [
            {
                "id": row["id"],
                "key": row["key"],
                "label": row["label"],
            }
            for row in packaging_rows
        ],
        "items": [
            {
                "itemId": row["id"],
                "condition": row["condition"],
                "purchasePrice": float(row["purchase_price"]) if row["purchase_price"] is not None else None,
                "purchasedAt": row["purchased_at"].isoformat() if row["purchased_at"] else None,
                "photos": row["photos"],
                "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
                "attributes": row["attributes"],
                "count": int(row["count"] or 0),
                "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
                "isPublished": row["is_published"],
                "notes": row["notes"],
                "carId": row["car_id"],
                "storageLocation": (
                    {
                        "id": row["storage_location_id"],
                        "name": row["storage_location_name"],
                    }
                    if row["storage_location_id"]
                    else None
                ),
            }
            for row in item_rows
        ],
    }


def upsert_collection_entries(user_id, items):
    conn = get_db_connection()
    created = []
    updated = []

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for item in items or []:
            item_id = item.get("itemId")
            storage_location_id = _get_or_create_storage_location(cur, user_id, item)

            if item_id:
                cur.execute(
                    """
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
                    RETURNING id, car_id
                    """,
                    (
                        _normalize_collection_condition(item.get("condition")),
                        item.get("purchasePrice"),
                        item.get("purchasedAt"),
                        Json(item.get("photos") or []),
                        Json(item.get("attributes") or {}),
                        _normalize_collection_count(item.get("count")),
                        item.get("notes"),
                        _normalize_collection_published(item.get("isPublished")),
                        storage_location_id,
                        item_id,
                        user_id,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError("Item not found")
                updated.append({"id": row["id"], "carId": row["car_id"]})
                continue

            cur.execute(
                """
                INSERT INTO user_collection_items
                (
                    user_id,
                    car_id,
                    condition,
                    purchase_price,
                    purchased_at,
                    photos,
                    attributes,
                    count,
                    notes,
                    is_published,
                    storage_location_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, car_id
                """,
                (
                    user_id,
                    item.get("carId"),
                    _normalize_collection_condition(item.get("condition")),
                    item.get("purchasePrice"),
                    item.get("purchasedAt"),
                    Json(item.get("photos") or []),
                    Json(item.get("attributes") or {}),
                    _normalize_collection_count(item.get("count")),
                    item.get("notes"),
                    _normalize_collection_published(item.get("isPublished")),
                    storage_location_id,
                ),
            )
            row = cur.fetchone()
            created.append({"id": row["id"], "carId": row["car_id"]})

    return {
        "message": "Success",
        "data": {
            "created": created,
            "updated": updated,
        },
    }


def delete_collection_entry(user_id, car_id, item_id=None, delete_all=False):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            DELETE FROM user_collection_storage
            WHERE user_id = %s
              AND car_id = %s
            RETURNING user_id, car_id
            """,
            (user_id, car_id),
        )
        storage_row = cur.fetchone()

        if item_id:
            cur.execute(
                """
                DELETE FROM user_collection_items
                WHERE id = %s
                  AND user_id = %s
                RETURNING id
                """,
                (item_id, user_id),
            )
        elif delete_all and car_id:
            cur.execute(
                """
                DELETE FROM user_collection_items
                WHERE car_id = %s
                  AND user_id = %s
                RETURNING id
                """,
                (car_id, user_id),
            )
        else:
            return {
                "message": "carId and deleteAll or itemId are required",
                "deleted": False,
                "userId": user_id,
                "carId": car_id,
                "deletedCount": 0,
            }

        rows = cur.fetchall()

    return {
        "message": "Item removed from inventory successfully",
        "deleted": storage_row is not None,
        "userId": user_id,
        "carId": car_id,
        "deletedCount": len(rows),
    }


def like_car(user_id, car_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO user_liked_items (user_id, car_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            RETURNING user_id, car_id
            """,
            (user_id, car_id),
        )
        row = cur.fetchone()

    return {
        "message": "Added to likes",
        "userId": user_id,
        "carId": car_id,
        "added": row is not None,
    }


def dislike_car(user_id, car_id):
    conn = get_db_connection()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            DELETE FROM user_liked_items
            WHERE user_id = %s
              AND car_id = %s
            RETURNING user_id, car_id
            """,
            (user_id, car_id),
        )
        row = cur.fetchone()

    return {
        "message": "Item removed from likes successfully",
        "deleted": row is not None,
        "userId": user_id,
        "carId": car_id,
    }
