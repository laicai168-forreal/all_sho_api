# app/repositories/user_repository.py

from app.common.db import get_db_connection


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
