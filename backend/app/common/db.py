# backend/app/common/db.py

import json
import boto3
import psycopg2
from psycopg2 import OperationalError, InterfaceError
import os

secrets_client = boto3.client("secretsmanager")

DB_SECRET = None
DB_CONN = None

SECRET_ARN = os.environ.get("DB_SECRET_ARN")
DB_NAME = os.environ.get("DB_NAME", "carsdb")


def get_db_connection():
    global DB_SECRET, DB_CONN

    if DB_SECRET is None:
        resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
        DB_SECRET = json.loads(resp["SecretString"])

    if DB_CONN is not None and not DB_CONN.closed:
        try:
            with DB_CONN.cursor() as cur:
                cur.execute("SELECT 1")
            return DB_CONN
        except (OperationalError, InterfaceError):
            try:
                DB_CONN.close()
            except Exception:
                pass
            DB_CONN = None

    if DB_CONN is None or DB_CONN.closed:
        DB_CONN = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_SECRET["username"],
            password=DB_SECRET["password"],
            host=DB_SECRET["host"],
            port=int(DB_SECRET.get("port", 5432)),
        )
        DB_CONN.autocommit = True

    return DB_CONN
