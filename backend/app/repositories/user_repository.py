# app/repositories/user_repository.py

from app.common.db import get_db_connection
from psycopg2 import IntegrityError


def create_user(sub, email, phone, username):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, username, cognito_sub, email, phone_number)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cognito_sub) DO UPDATE
            SET id = EXCLUDED.id,
                username = EXCLUDED.username,
                email = EXCLUDED.email,
                phone_number = EXCLUDED.phone_number
        """,
            (sub, username, sub, email, phone),
        )
    conn.commit()


def get_user_by_sub(sub):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE cognito_sub = %s", (sub,))
        row = cur.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))


def update_user(sub, bio, address, age, profile_image_url):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET bio = %s,
                address = %s,
                age = %s,
                profile_image_url = %s
            WHERE cognito_sub = %s
        """,
            (bio, address, age, profile_image_url, sub),
        )
        updated_rows = cur.rowcount

    conn.commit()
    return updated_rows


def update_user_role_by_sub(cognito_sub, role):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET role = %s
            WHERE cognito_sub = %s
        """,
            (role, cognito_sub),
        )
        updated_rows = cur.rowcount

    conn.commit()
    return updated_rows


def list_users(keyword=None, limit=50, offset=0):
    conn = get_db_connection()
    params = []
    where_clause = ""

    if keyword:
        where_clause = """
        WHERE
            username ILIKE %s
            OR email ILIKE %s
            OR cognito_sub ILIKE %s
        """
        keyword_pattern = f"%{keyword}%"
        params.extend([keyword_pattern, keyword_pattern, keyword_pattern])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, username, email, cognito_sub, role, profile_image_url, created_at
            FROM users
            {where_clause}
            ORDER BY created_at DESC, username ASC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM users
            {where_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

    return {
        "items": [dict(zip(columns, row)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def delete_user_by_id(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # The service layer treats a hard delete as best-effort: if the
            # schema blocks it with restrictive foreign keys, we report that
            # cleanly instead of masking the integrity failure.
            cur.execute(
                """
                DELETE FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            deleted_rows = cur.rowcount

        conn.commit()
        return {"deleted_rows": deleted_rows}
    except IntegrityError as error:
        conn.rollback()
        return {"deleted_rows": 0, "blocked_by_reference": True, "error": str(error)}


def get_user_by_id(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))


def get_public_profile(user_id, limit=12, offset=0):
    conn = get_db_connection()
    safe_limit = min(max(limit or 12, 1), 48)
    safe_offset = max(offset or 0, 0)

    with conn.cursor() as cur:
        # Public profile stays intentionally lightweight for now: user summary,
        # follower stats, and a paginated collection overview that we can later
        # reuse on feeds or trade/profile surfaces.
        cur.execute(
            """
            SELECT
                u.id,
                u.username,
                u.bio,
                u.profile_image_url,
                u.created_at,
                (
                    SELECT COUNT(*)
                    FROM user_follows uf
                    WHERE uf.followed_user_id = u.id
                ) AS followers_count,
                (
                    SELECT COUNT(*)
                    FROM user_follows uf
                    WHERE uf.follower_id = u.id
                ) AS following_count,
                (
                    SELECT COUNT(DISTINCT uci.car_id)
                    FROM user_collection_items uci
                    WHERE uci.user_id = u.id
                ) AS collections_count
            FROM users u
            WHERE u.id = %s
            """,
            (user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return None

        user_columns = [desc[0] for desc in cur.description]
        profile = dict(zip(user_columns, user_row))

        cur.execute(
            """
            SELECT COUNT(DISTINCT uci.car_id)
            FROM user_collection_items uci
            WHERE uci.user_id = %s
            """,
            (user_id,),
        )
        total_items = cur.fetchone()[0]

        cur.execute(
            """
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
            GROUP BY c.id, c.title, c.brand, c.original_id, c.images
            ORDER BY latest_added DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, safe_limit, safe_offset),
        )
        collection_rows = cur.fetchall()

    items = [
        {
            "carId": row[0],
            "title": row[1],
            "brand": row[2],
            "originalId": row[3],
            "images": row[4],
            "totalCount": row[5],
            "batchCount": row[6],
            "latestAdded": row[7].isoformat() if row[7] else None,
        }
        for row in collection_rows
    ]

    return {
        "user": {
            "id": profile["id"],
            "username": profile["username"],
            "bio": profile["bio"],
            "profile_image_url": profile["profile_image_url"],
            "created_at": profile["created_at"].isoformat() if profile["created_at"] else None,
        },
        "stats": {
            "followersCount": profile["followers_count"] or 0,
            "followingCount": profile["following_count"] or 0,
            "collectionsCount": profile["collections_count"] or 0,
        },
        "collections": {
            "items": items,
            "total": total_items,
            "limit": safe_limit,
            "offset": safe_offset,
        },
    }


def get_follow_status(follower_id, followed_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1
                FROM user_follows
                WHERE follower_id = %s AND followed_user_id = %s
            )
            """,
            (follower_id, followed_user_id),
        )
        following = cur.fetchone()[0]

        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1
                FROM user_follows
                WHERE follower_id = %s AND followed_user_id = %s
            )
            """,
            (followed_user_id, follower_id),
        )
        followed_by = cur.fetchone()[0]

    return {
        "following": following,
        "followedBy": followed_by,
        "isFriend": following and followed_by,
    }


def follow_user(follower_id, followed_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_follows (follower_id, followed_user_id)
            VALUES (%s, %s)
            ON CONFLICT (follower_id, followed_user_id) DO NOTHING
            """,
            (follower_id, followed_user_id),
        )
    conn.commit()


def unfollow_user(follower_id, followed_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM user_follows
            WHERE follower_id = %s AND followed_user_id = %s
            """,
            (follower_id, followed_user_id),
        )
    conn.commit()


def list_followers(user_id, limit=20, offset=0):
    conn = get_db_connection()
    safe_limit = min(max(limit or 20, 1), 100)
    safe_offset = max(offset or 0, 0)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM user_follows uf
            WHERE uf.followed_user_id = %s
            """,
            (user_id,),
        )
        total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT
                u.id,
                u.username,
                u.bio,
                u.profile_image_url,
                uf.created_at
            FROM user_follows uf
            JOIN users u ON u.id = uf.follower_id
            WHERE uf.followed_user_id = %s
            ORDER BY uf.created_at DESC, u.username ASC
            LIMIT %s OFFSET %s
            """,
            (user_id, safe_limit, safe_offset),
        )
        rows = cur.fetchall()

    return {
        "items": [
            {
                "id": row[0],
                "username": row[1],
                "bio": row[2],
                "profile_image_url": row[3],
                "followed_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


def list_following(user_id, limit=20, offset=0):
    conn = get_db_connection()
    safe_limit = min(max(limit or 20, 1), 100)
    safe_offset = max(offset or 0, 0)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM user_follows uf
            WHERE uf.follower_id = %s
            """,
            (user_id,),
        )
        total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT
                u.id,
                u.username,
                u.bio,
                u.profile_image_url,
                uf.created_at
            FROM user_follows uf
            JOIN users u ON u.id = uf.followed_user_id
            WHERE uf.follower_id = %s
            ORDER BY uf.created_at DESC, u.username ASC
            LIMIT %s OFFSET %s
            """,
            (user_id, safe_limit, safe_offset),
        )
        rows = cur.fetchall()

    return {
        "items": [
            {
                "id": row[0],
                "username": row[1],
                "bio": row[2],
                "profile_image_url": row[3],
                "followed_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


def remove_follower(user_id, follower_user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM user_follows
            WHERE follower_id = %s AND followed_user_id = %s
            """,
            (follower_user_id, user_id),
        )
    conn.commit()
