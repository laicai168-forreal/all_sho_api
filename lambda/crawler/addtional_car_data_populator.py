import boto3
import requests
import logging
import os
from psycopg2.extras import execute_values
import psycopg2
import json
from datetime import date
import time

# CONFIG via env vars
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE_NAME", "CrawlerLogsTable")


# AWS clients
secrets_client = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")

log_table = dynamodb.Table(LOGS_TABLE_NAME)

def get_db_credentials():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret = json.loads(resp["SecretString"])
    return {
        "host": secret.get("host"),
        "username": secret.get("username"),
        "password": secret.get("password"),
        "port": int(secret.get("port", 5432)),
    }


def combine_month_year(metadata):
    """
    metadata: {"release_month": 4, "release_year": 2024, ...}
    """
    year = metadata.get("release_year")
    month = metadata.get("release_month") or 1

    return date(year, month, 1)


def update_ai_metadata_only(conn, items, a_version):
    with conn.cursor() as cur:
        sql = """
        UPDATE cars
        SET release_date_ai = %s,
            description_ai  = %s,
            make_ai         = %s,
            model_ai        = %s,
            a_ver           = %s
        WHERE id = %s
        """
        for it in items:
            release_date = combine_month_year(it)
            cur.execute(
                sql,
                (
                    release_date,
                    it.get("description"),
                    it.get("make"),
                    it.get("model"),
                    a_version,
                    it["id"],
                ),
            )
        conn.commit()


def get_db_conn(creds):
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=creds["username"],
        password=creds["password"],
        host=creds["host"],
        port=creds["port"],
    )

    return conn


def get_cars_to_update(conn, new_a_ver, limit, log):
    items = []
    data_query = f"""
        SELECT id, title, brand
        FROM cars
        WHERE a_ver IS NULL OR a_ver < %s
    """

    if limit:
        data_query += f" LIMIT {limit}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(data_query, (new_a_ver,))
        items = cur.fetchall()
        items = [
            {**t, 'title': f'{t['brand']}, {t['title']}'}
            for t in items
        ]

    log(f'Updated {', '.join([i['id'] for i in items])}')
    return items


# DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_API_KEY = "sk-3f588e99303e428b995c7632d2f30349"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


def fetch_deepseek_car_metadata(items, log):
    prompt = f"""
    You are an expert diecast model researcher.  
    Given the following array of diecast model names:

    {json.dumps(items)}

    For each item, return STRICT JSON ONLY (no explanation, no commentary).  
    Return an array in the SAME ORDER as the input.

    Each item must be an object like:
    {{
        "id": "exact id of the car from my input",
        "release_month": number,
        "release_year": number,
        "description": "short profile about this car",
        "make": "car make",
        "model": "car model"
    }}

    Rules:
        - The id should be the exact ID I provide for corresponding item
        - If the release date is approximate (quarter only), use:
            Q1 → 1
            Q2 → 4
            Q3 → 7
            Q4 → 10
        - “make” must be the real automotive brand (Porsche, Toyota, etc.), give NULL for unrecognized ones
        - “model” must be the specific car model (911 GT3 R, Hiace, etc.)
        - JSON MUST BE VALID.
    """

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }

    try:
        res = requests.post(DEEPSEEK_URL, headers=headers, json=body)
        res.raise_for_status()
    except Exception as e:
        log(f'Failed to communicate with AI agent. Error message: {e}')
        log(f"END")


    # The model's response with JSON
    content = res.json()["choices"][0]["message"]["content"].strip()

    return json.loads(content)


# Lambda handler
def handler(event, context):
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])
    else:
        body = event

    job_id = body.get("job_id")
    ONE_MONTH = 30 * 24 * 60 * 60

    def log(msg):
        ts = int(time.time() * 1000)
        print(f"[JOB {job_id}] {msg}")
        log_table.put_item(
        Item={
                "jobId": job_id,
                "ts": ts,
                "message": msg,
                "expireAt": int(time.time()) + ONE_MONTH,
            }
        )

    log("Start populating car additional data...")

    try:
        a_version = body.get("a_version", 0)
        limit = body.get("limit")

        creds = get_db_credentials()
        conn = get_db_conn(creds)

        items_to_update = get_cars_to_update(conn, a_version, limit, log)
        items_to_insert = fetch_deepseek_car_metadata(items_to_update, log)
        log(f"Getting new data from AI: {items_to_insert}")

        if len(items_to_insert) > 0:
            update_ai_metadata_only(conn, items_to_insert, a_version)

        conn.close()

        log("DONE")

        return {
                "statusCode": 200,
                "body": json.dumps({
                    "updated_items": [t['id'] for t in items_to_insert]
                })
            }

    except Exception as e:
        log(f"Failed to crawl: {e}")
        log(f"END")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


# If run locally
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Crawl Mini GT product pages to AWS")
    parser.add_argument("--catalog", help="Catalog URL to crawl from")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument(
        "--product-urls", nargs="*", help="Specific product pages to crawl"
    )
    args = parser.parse_args()
    event = {}
    if args.product_urls:
        event["product_urls"] = args.product_urls
    if args.catalog:
        event["catalog_url"] = args.catalog
        event["max_pages"] = args.max_pages
    out = handler(event, None)
    print(json.dumps(out, indent=2))
