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
