import uuid
from decimal import Decimal

from app.common.db import get_db_connection
from psycopg2 import IntegrityError


def _normalize_post_row(row):
    if not row:
        return None

    return {
        "id": str(row[0]),
        "post_type": row[1],
        "title": row[2],
        "description": row[3],
        "visibility": row[4],
        "status": row[5],
        "like_count": row[6],
        "comment_count": row[7],
        "image_count": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
        "published_at": row[11].isoformat() if row[11] else None,
        "author": {
            "id": str(row[12]),
            "username": row[13],
            "profile_image_url": row[14],
        },
        "selling_details": {
            "price": float(row[15]) if isinstance(row[15], Decimal) else row[15],
            "currency": row[16],
            "condition": row[17],
            "location": row[18],
            "shipping_supported": row[19],
            "selling_status": row[20],
        } if row[15] is not None else None,
        "images": row[21] or [],
        "tags": row[22] or [],
        "cars": row[23] or [],
    }


def _normalize_sale_transaction_row(row):
    if not row:
        return None

    return {
        "id": str(row[0]),
        "post_id": str(row[1]),
        "seller_user_id": str(row[2]),
        "buyer": {
            "id": str(row[3]),
            "username": row[4],
            "profile_image_url": row[5],
        },
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }


def _normalize_comment_row(row):
    if not row:
        return None

    return {
        "id": str(row[0]),
        "post_id": str(row[1]),
        "content": row[2],
        "status": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
        "updated_at": row[5].isoformat() if row[5] else None,
        "author": {
            "id": str(row[6]),
            "username": row[7],
            "profile_image_url": row[8],
        },
    }


def _normalize_transaction_review_row(row):
    if not row:
        return None

    return {
        "id": str(row[0]),
        "showroom_post_id": str(row[1]),
        "rating": int(row[2]),
        "comment": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
        "reviewer": {
            "id": str(row[5]),
            "username": row[6],
            "profile_image_url": row[7],
        },
        "reviewee": {
            "id": str(row[8]),
            "username": row[9],
            "profile_image_url": row[10],
        },
        "showroom_post": {
            "id": str(row[11]),
            "title": row[12],
        },
    }


def create_showroom_post(*, post_id, user_id, post_type, title, description, visibility, tags, car_ids, images, selling_details):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO showroom_posts (
                    id, user_id, post_type, title, description, visibility, status, image_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'published', %s)
                """,
                (post_id, user_id, post_type, title, description, visibility, len(images)),
            )

            if post_type == "selling" and selling_details:
                cur.execute(
                    """
                    INSERT INTO showroom_selling_details (
                        post_id, price, currency, condition, location, shipping_supported, selling_status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'available')
                    """,
                    (
                        post_id,
                        selling_details.get("price"),
                        selling_details.get("currency"),
                        selling_details.get("condition"),
                        selling_details.get("location"),
                        bool(selling_details.get("shippingSupported")),
                    ),
                )

            for index, image in enumerate(images):
                cur.execute(
                    """
                    INSERT INTO showroom_post_images (id, post_id, image_url, object_key, sort_order)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        post_id,
                        image.get("fileUrl"),
                        image.get("objectKey"),
                        image.get("sortOrder", index),
                    ),
                )

            for index, car_id in enumerate(car_ids):
                cur.execute(
                    """
                    INSERT INTO showroom_post_car_links (post_id, car_id, sort_order)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (post_id, car_id) DO NOTHING
                    """,
                    (post_id, car_id, index),
                )

            for tag in tags:
                cur.execute(
                    """
                    INSERT INTO showroom_tags (id, tag_key, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (tag_key) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                    RETURNING id
                    """,
                    (str(uuid.uuid4()), tag["tag_key"], tag["display_name"]),
                )
                tag_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO showroom_post_tag_links (post_id, tag_id)
                    VALUES (%s, %s)
                    ON CONFLICT (post_id, tag_id) DO NOTHING
                    """,
                    (post_id, tag_id),
                )

        conn.commit()
        return post_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def update_showroom_post(*, post_id, user_id, post_type, title, description, visibility, tags, car_ids, images, selling_details):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE showroom_posts
                SET post_type = %s,
                    title = %s,
                    description = %s,
                    visibility = %s,
                    image_count = %s,
                    updated_at = now()
                WHERE id = %s AND user_id = %s AND status = 'published'
                """,
                (post_type, title, description, visibility, len(images), post_id, user_id),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return {"updated": False}

            if post_type == "selling" and selling_details:
                cur.execute(
                    """
                    INSERT INTO showroom_selling_details (
                        post_id, price, currency, condition, location, shipping_supported, selling_status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'available')
                    ON CONFLICT (post_id) DO UPDATE
                    SET price = EXCLUDED.price,
                        currency = EXCLUDED.currency,
                        condition = EXCLUDED.condition,
                        location = EXCLUDED.location,
                        shipping_supported = EXCLUDED.shipping_supported
                    """,
                    (
                        post_id,
                        selling_details.get("price"),
                        selling_details.get("currency"),
                        selling_details.get("condition"),
                        selling_details.get("location"),
                        bool(selling_details.get("shippingSupported")),
                    ),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM showroom_selling_details
                    WHERE post_id = %s
                    """,
                    (post_id,),
                )

            cur.execute(
                """
                DELETE FROM showroom_post_images
                WHERE post_id = %s
                """,
                (post_id,),
            )
            for index, image in enumerate(images):
                cur.execute(
                    """
                    INSERT INTO showroom_post_images (id, post_id, image_url, object_key, sort_order)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        post_id,
                        image.get("fileUrl"),
                        image.get("objectKey"),
                        image.get("sortOrder", index),
                    ),
                )

            cur.execute(
                """
                DELETE FROM showroom_post_car_links
                WHERE post_id = %s
                """,
                (post_id,),
            )
            for index, car_id in enumerate(car_ids):
                cur.execute(
                    """
                    INSERT INTO showroom_post_car_links (post_id, car_id, sort_order)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (post_id, car_id) DO NOTHING
                    """,
                    (post_id, car_id, index),
                )

            cur.execute(
                """
                DELETE FROM showroom_post_tag_links
                WHERE post_id = %s
                """,
                (post_id,),
            )
            for tag in tags:
                cur.execute(
                    """
                    INSERT INTO showroom_tags (id, tag_key, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (tag_key) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                    RETURNING id
                    """,
                    (str(uuid.uuid4()), tag["tag_key"], tag["display_name"]),
                )
                tag_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO showroom_post_tag_links (post_id, tag_id)
                    VALUES (%s, %s)
                    ON CONFLICT (post_id, tag_id) DO NOTHING
                    """,
                    (post_id, tag_id),
                )

        conn.commit()
        return {"updated": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def update_showroom_selling_status(*, post_id, user_id, selling_status):
    conn = get_db_connection()

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE showroom_selling_details ssd
            SET selling_status = %s
            FROM showroom_posts sp
            WHERE ssd.post_id = sp.id
              AND sp.id = %s
              AND sp.user_id = %s
              AND sp.post_type = 'selling'
              AND sp.status = 'published'
            """,
            (selling_status, post_id, user_id),
        )
        updated = cur.rowcount > 0

    conn.commit()
    return {"updated": updated}


def get_showroom_sale_transaction(post_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                sst.id,
                sst.post_id,
                sst.seller_user_id,
                buyer.id,
                buyer.username,
                buyer.profile_image_url,
                sst.created_at,
                sst.updated_at
            FROM showroom_sale_transactions sst
            JOIN users buyer ON buyer.id = sst.buyer_user_id
            WHERE sst.post_id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()
    return _normalize_sale_transaction_row(row)


def upsert_showroom_sale_transaction(*, post_id, seller_user_id, buyer_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO showroom_sale_transactions (
                id, post_id, seller_user_id, buyer_user_id
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (post_id) DO UPDATE
            SET buyer_user_id = EXCLUDED.buyer_user_id,
                seller_user_id = EXCLUDED.seller_user_id,
                updated_at = now()
            """,
            (str(uuid.uuid4()), post_id, seller_user_id, buyer_user_id),
        )
    conn.commit()
    return get_showroom_sale_transaction(post_id)


def delete_showroom_sale_transaction(post_id, seller_user_id=None):
    conn = get_db_connection()
    with conn.cursor() as cur:
        if seller_user_id:
            cur.execute(
                """
                DELETE FROM showroom_sale_transactions
                WHERE post_id = %s AND seller_user_id = %s
                """,
                (post_id, seller_user_id),
            )
        else:
            cur.execute(
                """
                DELETE FROM showroom_sale_transactions
                WHERE post_id = %s
                """,
                (post_id,),
            )
        deleted = cur.rowcount > 0
    conn.commit()
    return {"deleted": deleted}


def _post_select_sql(where_clause: str):
    return f"""
        SELECT
            sp.id,
            sp.post_type,
            sp.title,
            sp.description,
            sp.visibility,
            sp.status,
            sp.like_count,
            sp.comment_count,
            sp.image_count,
            sp.created_at,
            sp.updated_at,
            sp.published_at,
            u.id AS author_id,
            u.username,
            u.profile_image_url,
            ssd.price,
            ssd.currency,
            ssd.condition,
            ssd.location,
            ssd.shipping_supported,
            ssd.selling_status,
            COALESCE((
                SELECT json_agg(
                    json_build_object(
                        'imageUrl', spi.image_url,
                        'sortOrder', spi.sort_order
                    )
                    ORDER BY spi.sort_order ASC
                )
                FROM showroom_post_images spi
                WHERE spi.post_id = sp.id
            ), '[]'::json) AS images,
            COALESCE((
                SELECT json_agg(st.display_name ORDER BY st.display_name ASC)
                FROM showroom_post_tag_links sptl
                JOIN showroom_tags st ON st.id = sptl.tag_id
                WHERE sptl.post_id = sp.id
            ), '[]'::json) AS tags,
            COALESCE((
                SELECT json_agg(
                    json_build_object(
                        'id', c.id,
                        'title', c.title,
                        'brand', c.brand,
                        'originalId', c.original_id,
                        'images', c.images
                    )
                    ORDER BY spcl.sort_order ASC
                )
                FROM showroom_post_car_links spcl
                JOIN cars c ON c.id = spcl.car_id
                WHERE spcl.post_id = sp.id
            ), '[]'::json) AS cars
        FROM showroom_posts sp
        JOIN users u ON u.id = sp.user_id
        LEFT JOIN showroom_selling_details ssd ON ssd.post_id = sp.id
        {where_clause}
    """


def get_showroom_post(post_id, actor_id=None, include_hidden=False):
    conn = get_db_connection()
    where_clause = ["sp.id = %s"]
    params = [post_id]

    if include_hidden:
        where_clause.append("sp.status IN ('published', 'hidden')")
    else:
        where_clause.append("sp.status = 'published'")

    if actor_id:
        where_clause.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM user_blocks ub
                WHERE (ub.blocker_id = %s AND ub.blocked_user_id = sp.user_id)
                   OR (ub.blocker_id = sp.user_id AND ub.blocked_user_id = %s)
            )
            """
        )
        params.extend([actor_id, actor_id])

    with conn.cursor() as cur:
        cur.execute(
            _post_select_sql(f"WHERE {' AND '.join(where_clause)}"),
            params,
        )
        row = cur.fetchone()
    return _normalize_post_row(row)


def get_showroom_comment(comment_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                spc.id,
                spc.post_id,
                spc.content,
                spc.status,
                spc.created_at,
                spc.updated_at,
                u.id,
                u.username,
                u.profile_image_url
            FROM showroom_post_comments spc
            JOIN users u ON u.id = spc.user_id
            WHERE spc.id = %s
            """,
            (comment_id,),
        )
        row = cur.fetchone()
    return _normalize_comment_row(row)


def get_showroom_post_like_status(post_id, user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM showroom_post_likes
                WHERE post_id = %s AND user_id = %s
            )
            """,
            (post_id, user_id),
        )
        return bool(cur.fetchone()[0])


def list_showroom_comments(post_id, limit=30, offset=0, actor_id=None):
    safe_limit = min(max(limit or 30, 1), 100)
    safe_offset = max(offset or 0, 0)
    conn = get_db_connection()
    block_clause = ""
    params = [post_id]

    if actor_id:
        block_clause = """
            AND NOT EXISTS (
                SELECT 1
                FROM user_blocks ub
                WHERE (ub.blocker_id = %s AND ub.blocked_user_id = spc.user_id)
                   OR (ub.blocker_id = spc.user_id AND ub.blocked_user_id = %s)
            )
        """
        params.extend([actor_id, actor_id])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                spc.id,
                spc.post_id,
                spc.content,
                spc.status,
                spc.created_at,
                spc.updated_at,
                u.id,
                u.username,
                u.profile_image_url
            FROM showroom_post_comments spc
            JOIN users u ON u.id = spc.user_id
            WHERE spc.post_id = %s AND spc.status = 'published'
            {block_clause}
            ORDER BY spc.created_at ASC
            LIMIT %s OFFSET %s
            """,
            params + [safe_limit, safe_offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM showroom_post_comments spc
            WHERE post_id = %s AND status = 'published'
            {block_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

    return {
        "items": [_normalize_comment_row(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


def create_showroom_comment(*, post_id, user_id, content):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit
    comment_id = str(uuid.uuid4())

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO showroom_post_comments (id, post_id, user_id, content)
                VALUES (%s, %s, %s, %s)
                """,
                (comment_id, post_id, user_id, content),
            )
            cur.execute(
                """
                UPDATE showroom_posts
                SET comment_count = comment_count + 1,
                    updated_at = now()
                WHERE id = %s
                """,
                (post_id,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                spc.id,
                spc.post_id,
                spc.content,
                spc.status,
                spc.created_at,
                spc.updated_at,
                u.id,
                u.username,
                u.profile_image_url
            FROM showroom_post_comments spc
            JOIN users u ON u.id = spc.user_id
            WHERE spc.id = %s
            """,
            (comment_id,),
        )
        row = cur.fetchone()
    return _normalize_comment_row(row)


def delete_showroom_comment(*, comment_id, user_id):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT post_id
                FROM showroom_post_comments
                WHERE id = %s AND user_id = %s AND status = 'published'
                """,
                (comment_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return {"deleted": False}

            post_id = row[0]
            cur.execute(
                """
                UPDATE showroom_post_comments
                SET status = 'deleted',
                    updated_at = now()
                WHERE id = %s
                """,
                (comment_id,),
            )
            cur.execute(
                """
                UPDATE showroom_posts
                SET comment_count = GREATEST(comment_count - 1, 0),
                    updated_at = now()
                WHERE id = %s
                """,
                (post_id,),
            )
        conn.commit()
        return {"deleted": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def list_showroom_transaction_reviews(showroom_post_id, seller_user_id, buyer_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                strv.id,
                strv.showroom_post_id,
                strv.rating,
                strv.comment,
                strv.created_at,
                reviewer.id,
                reviewer.username,
                reviewer.profile_image_url,
                reviewee.id,
                reviewee.username,
                reviewee.profile_image_url,
                sp.id,
                sp.title
            FROM showroom_transaction_reviews strv
            JOIN users reviewer ON reviewer.id = strv.reviewer_user_id
            JOIN users reviewee ON reviewee.id = strv.reviewee_user_id
            JOIN showroom_posts sp ON sp.id = strv.showroom_post_id
            WHERE strv.showroom_post_id = %s
              AND strv.seller_user_id = %s
              AND strv.buyer_user_id = %s
            ORDER BY strv.created_at ASC
            """,
            (showroom_post_id, seller_user_id, buyer_user_id),
        )
        rows = cur.fetchall()
    return [_normalize_transaction_review_row(row) for row in rows]


def create_showroom_transaction_review(*, showroom_post_id, seller_user_id, buyer_user_id, reviewer_user_id, reviewee_user_id, rating, comment):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO showroom_transaction_reviews (
                    id,
                    showroom_post_id,
                    seller_user_id,
                    buyer_user_id,
                    reviewer_user_id,
                    reviewee_user_id,
                    rating,
                    comment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(uuid.uuid4()),
                    showroom_post_id,
                    seller_user_id,
                    buyer_user_id,
                    reviewer_user_id,
                    reviewee_user_id,
                    rating,
                    comment,
                ),
            )
            review_id = cur.fetchone()[0]
        conn.commit()
        return str(review_id)
    except IntegrityError:
        conn.rollback()
        return None


def get_user_review_summary(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*),
                AVG(rating)
            FROM showroom_transaction_reviews
            WHERE reviewee_user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()

    total = int(row[0] or 0)
    average = float(row[1]) if row and row[1] is not None else None
    return {
        "totalReviews": total,
        "averageRating": average,
    }


def list_recent_user_reviews(user_id, limit=6, offset=0):
    safe_limit = min(max(limit or 6, 1), 20)
    safe_offset = max(offset or 0, 0)
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                strv.id,
                strv.showroom_post_id,
                strv.rating,
                strv.comment,
                strv.created_at,
                reviewer.id,
                reviewer.username,
                reviewer.profile_image_url,
                reviewee.id,
                reviewee.username,
                reviewee.profile_image_url,
                sp.id,
                sp.title
            FROM showroom_transaction_reviews strv
            JOIN users reviewer ON reviewer.id = strv.reviewer_user_id
            JOIN users reviewee ON reviewee.id = strv.reviewee_user_id
            JOIN showroom_posts sp ON sp.id = strv.showroom_post_id
            WHERE strv.reviewee_user_id = %s
            ORDER BY strv.created_at DESC
            LIMIT %s
            OFFSET %s
            """,
            (user_id, safe_limit, safe_offset),
        )
        rows = cur.fetchall()
    return [_normalize_transaction_review_row(row) for row in rows]


def like_showroom_post(*, post_id, user_id):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit
    created = False

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO showroom_post_likes (post_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (post_id, user_id) DO NOTHING
                """,
                (post_id, user_id),
            )
            created = cur.rowcount > 0
            if created:
                cur.execute(
                    """
                    UPDATE showroom_posts
                    SET like_count = like_count + 1,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (post_id,),
                )
        conn.commit()
        return {"liked": created}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def unlike_showroom_post(*, post_id, user_id):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit
    removed = False

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM showroom_post_likes
                WHERE post_id = %s AND user_id = %s
                """,
                (post_id, user_id),
            )
            removed = cur.rowcount > 0
            if removed:
                cur.execute(
                    """
                    UPDATE showroom_posts
                    SET like_count = GREATEST(like_count - 1, 0),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (post_id,),
                )
        conn.commit()
        return {"unliked": removed}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def delete_showroom_post(*, post_id, user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE showroom_posts
            SET status = 'deleted',
                updated_at = now()
            WHERE id = %s AND user_id = %s AND status = 'published'
            """,
            (post_id, user_id),
        )
        deleted = cur.rowcount > 0
    return {"deleted": deleted}


def count_recent_showroom_posts(user_id, window_minutes=60):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM showroom_posts
            WHERE user_id = %s
              AND created_at >= now() - (%s || ' minutes')::interval
            """,
            (user_id, window_minutes),
        )
        return cur.fetchone()[0]


def count_recent_showroom_comments(user_id, window_minutes=10):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM showroom_post_comments
            WHERE user_id = %s
              AND created_at >= now() - (%s || ' minutes')::interval
            """,
            (user_id, window_minutes),
        )
        return cur.fetchone()[0]


def count_recent_showroom_reports(user_id, window_minutes=60):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM showroom_reports
            WHERE reporter_id = %s
              AND created_at >= now() - (%s || ' minutes')::interval
            """,
            (user_id, window_minutes),
        )
        return cur.fetchone()[0]


def create_showroom_report(*, reporter_id, reason, details=None, post_id=None, comment_id=None):
    conn = get_db_connection()
    report_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO showroom_reports (id, reporter_id, post_id, comment_id, reason, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, reporter_id, post_id, comment_id, reason, details, status, created_at, reviewed_at, reviewed_by, review_notes
            """,
            (report_id, reporter_id, post_id, comment_id, reason, details),
        )
        row = cur.fetchone()
    return {
        "id": str(row[0]),
        "reporterId": str(row[1]),
        "postId": str(row[2]) if row[2] else None,
        "commentId": str(row[3]) if row[3] else None,
        "reason": row[4],
        "details": row[5],
        "status": row[6],
        "createdAt": row[7].isoformat() if row[7] else None,
        "reviewedAt": row[8].isoformat() if row[8] else None,
        "reviewedBy": str(row[9]) if row[9] else None,
        "reviewNotes": row[10],
    }


def list_showroom_reports(limit=50, offset=0, status=None):
    safe_limit = min(max(limit or 50, 1), 100)
    safe_offset = max(offset or 0, 0)
    conn = get_db_connection()
    params = []
    where_clause = ""
    if status:
        where_clause = "WHERE sr.status = %s"
        params.append(status)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                sr.id,
                sr.reporter_id,
                reporter.username,
                sr.post_id,
                sp.title,
                sr.comment_id,
                spc.content,
                sr.reason,
                sr.details,
                sr.status,
                sr.created_at,
                sr.reviewed_at,
                sr.reviewed_by,
                reviewer.username,
                sr.review_notes
            FROM showroom_reports sr
            JOIN users reporter ON reporter.id = sr.reporter_id
            LEFT JOIN showroom_posts sp ON sp.id = sr.post_id
            LEFT JOIN showroom_post_comments spc ON spc.id = sr.comment_id
            LEFT JOIN users reviewer ON reviewer.id = sr.reviewed_by
            {where_clause}
            ORDER BY sr.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [safe_limit, safe_offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM showroom_reports sr
            {where_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

    return {
        "items": [
            {
                "id": str(row[0]),
                "reporterId": str(row[1]),
                "reporterUsername": row[2],
                "postId": str(row[3]) if row[3] else None,
                "postTitle": row[4],
                "commentId": str(row[5]) if row[5] else None,
                "commentContent": row[6],
                "reason": row[7],
                "details": row[8],
                "status": row[9],
                "createdAt": row[10].isoformat() if row[10] else None,
                "reviewedAt": row[11].isoformat() if row[11] else None,
                "reviewedBy": str(row[12]) if row[12] else None,
                "reviewedByUsername": row[13],
                "reviewNotes": row[14],
            }
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


def update_showroom_post_status(post_id, status):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE showroom_posts
            SET status = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (status, post_id),
        )
        updated = cur.rowcount > 0
    return {"updated": updated}


def update_showroom_comment_status(comment_id, status):
    conn = get_db_connection()
    previous_autocommit = conn.autocommit
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT post_id, status
                FROM showroom_post_comments
                WHERE id = %s
                """,
                (comment_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return {"updated": False}

            post_id, old_status = row
            cur.execute(
                """
                UPDATE showroom_post_comments
                SET status = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (status, comment_id),
            )

            if old_status != status:
                if old_status == "published" and status == "deleted":
                    cur.execute(
                        """
                        UPDATE showroom_posts
                        SET comment_count = GREATEST(comment_count - 1, 0),
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (post_id,),
                    )
                elif old_status == "deleted" and status == "published":
                    cur.execute(
                        """
                        UPDATE showroom_posts
                        SET comment_count = comment_count + 1,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (post_id,),
                    )
        conn.commit()
        return {"updated": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit


def resolve_showroom_report(report_id, reviewer_id, status, review_notes=None):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE showroom_reports
            SET status = %s,
                reviewed_at = now(),
                reviewed_by = %s,
                review_notes = %s
            WHERE id = %s
            """,
            (status, reviewer_id, review_notes, report_id),
        )
        updated = cur.rowcount > 0
    return {"updated": updated}


def _build_showroom_feed_sql_parts(
    *,
    user_id=None,
    post_type=None,
    feed_mode="recent",
    actor_id=None,
    tag_key=None,
    car_id=None,
    keyword=None,
    seller_query=None,
    min_price=None,
    max_price=None,
    shipping_supported=None,
    selling_status=None,
):
    joins = []
    conditions = [
        "sp.status = 'published'",
        "sp.visibility = 'public'",
    ]
    join_params = []
    condition_params = []

    if user_id:
        conditions.append("sp.user_id = %s")
        condition_params.append(user_id)

    if post_type:
        conditions.append("sp.post_type = %s")
        condition_params.append(post_type)
    if tag_key:
        joins.append(
            """
            JOIN showroom_post_tag_links sptl_filter
              ON sptl_filter.post_id = sp.id
            JOIN showroom_tags st_filter
              ON st_filter.id = sptl_filter.tag_id
             AND st_filter.tag_key = %s
            """
        )
        join_params.append(tag_key)
    if car_id:
        joins.append(
            """
            JOIN showroom_post_car_links spcl_filter
              ON spcl_filter.post_id = sp.id
             AND spcl_filter.car_id = %s
            """
        )
        join_params.append(car_id)
    if keyword:
        conditions.append("(sp.title ILIKE %s OR sp.description ILIKE %s)")
        keyword_pattern = f"%{keyword}%"
        condition_params.append(keyword_pattern)
        condition_params.append(keyword_pattern)
    if seller_query:
        conditions.append("u.username ILIKE %s")
        condition_params.append(f"%{seller_query}%")
    if min_price is not None:
        conditions.append("ssd.price >= %s")
        condition_params.append(min_price)
    if max_price is not None:
        conditions.append("ssd.price <= %s")
        condition_params.append(max_price)
    if shipping_supported is not None:
        conditions.append("ssd.shipping_supported = %s")
        condition_params.append(shipping_supported)
    if selling_status:
        conditions.append("ssd.selling_status = %s")
        condition_params.append(selling_status)
    if actor_id:
        conditions.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM user_blocks ub
                WHERE (ub.blocker_id = %s AND ub.blocked_user_id = sp.user_id)
                   OR (ub.blocker_id = sp.user_id AND ub.blocked_user_id = %s)
            )
            """
        )
        condition_params.append(actor_id)
        condition_params.append(actor_id)

    if feed_mode == "following":
        joins.append(
            """
            JOIN user_follows uf
              ON uf.followed_user_id = sp.user_id
             AND uf.follower_id = %s
            """
        )
        join_params.append(actor_id)
    elif feed_mode == "friends":
        joins.append(
            """
            JOIN user_follows uf_out
              ON uf_out.followed_user_id = sp.user_id
             AND uf_out.follower_id = %s
            """
        )
        joins.append(
            """
            JOIN user_follows uf_in
              ON uf_in.follower_id = sp.user_id
             AND uf_in.followed_user_id = %s
            """
        )
        join_params.append(actor_id)
        join_params.append(actor_id)
    elif feed_mode == "hot_topics":
        conditions.append("COALESCE(sp.published_at, sp.created_at) >= now() - interval '45 days'")
    elif feed_mode == "popular":
        conditions.append("COALESCE(sp.published_at, sp.created_at) >= now() - interval '90 days'")

    where_clause = f"WHERE {' AND '.join(conditions)}"
    join_clause = " ".join(joins)
    return join_clause, where_clause, join_params + condition_params


def _showroom_feed_order_by(feed_mode):
    if feed_mode == "hot_topics":
        return """
            ORDER BY
                (
                    sp.comment_count * 5
                    + sp.like_count * 3
                    + COALESCE((
                        SELECT COUNT(*)
                        FROM showroom_post_tag_links sptl
                        WHERE sptl.post_id = sp.id
                    ), 0) * 4
                ) DESC,
                COALESCE(sp.published_at, sp.created_at) DESC
        """

    if feed_mode == "popular":
        return """
            ORDER BY
                (sp.comment_count * 5 + sp.like_count * 3) DESC,
                COALESCE(sp.published_at, sp.created_at) DESC
        """

    return """
        ORDER BY
            COALESCE(sp.published_at, sp.created_at) DESC,
            sp.created_at DESC
    """


def list_trending_showroom_tags(limit=12):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                st.tag_key,
                st.display_name,
                COUNT(*) AS post_count
            FROM showroom_post_tag_links sptl
            JOIN showroom_tags st ON st.id = sptl.tag_id
            JOIN showroom_posts sp ON sp.id = sptl.post_id
            WHERE sp.status = 'published'
              AND sp.visibility = 'public'
              AND COALESCE(sp.published_at, sp.created_at) >= now() - interval '45 days'
            GROUP BY st.tag_key, st.display_name
            ORDER BY post_count DESC, st.display_name ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [
        {
            "tagKey": row[0],
            "displayName": row[1],
            "postCount": row[2],
        }
        for row in rows
    ]


def list_showroom_posts(
    limit=20,
    offset=0,
    user_id=None,
    post_type=None,
    feed_mode="recent",
    actor_id=None,
    tag_key=None,
    car_id=None,
    keyword=None,
    seller_query=None,
    min_price=None,
    max_price=None,
    shipping_supported=None,
    selling_status=None,
):
    safe_limit = min(max(limit or 20, 1), 30)
    safe_offset = max(offset or 0, 0)
    conn = get_db_connection()
    join_clause, where_clause, params = _build_showroom_feed_sql_parts(
        user_id=user_id,
        post_type=post_type,
        feed_mode=feed_mode,
        actor_id=actor_id,
        tag_key=tag_key,
        car_id=car_id,
        keyword=keyword,
        seller_query=seller_query,
        min_price=min_price,
        max_price=max_price,
        shipping_supported=shipping_supported,
        selling_status=selling_status,
    )
    order_by_clause = _showroom_feed_order_by(feed_mode)

    with conn.cursor() as cur:
        cur.execute(
            _post_select_sql(f"{join_clause} {where_clause}") + f"""
            {order_by_clause}
            LIMIT %s OFFSET %s
            """,
            params + [safe_limit, safe_offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM showroom_posts sp
            LEFT JOIN showroom_selling_details ssd ON ssd.post_id = sp.id
            {join_clause}
            {where_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

    return {
        "items": [_normalize_post_row(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }
