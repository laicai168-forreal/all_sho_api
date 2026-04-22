import boto3
import requests
from io import BytesIO
from bs4 import BeautifulSoup
import time
import hashlib
import datetime
import logging
import os
import urllib.parse
from psycopg2.extras import execute_values, RealDictCursor
import psycopg2
import json
import time
import traceback
from urllib.parse import urlparse
import re
import unicodedata

# CONFIG via env vars
S3_BUCKET = os.environ.get("BUCKET_NAME", "DiecastDataBucket")
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
USER_AGENT = os.environ.get("USER_AGENT", "CarCrawler/1.0 Python/requests")
LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE_NAME", "CrawlerLogsTable")

region = os.environ.get("AWS_REGION", "us-east-1")

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.5"))

# AWS clients
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
log_table = dynamodb.Table(LOGS_TABLE_NAME)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NORMALIZATION_CACHE = {
    "brands": {},
    "makes": {},
    "product_lines": {}
}

cors_headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type": "application/json",
}

def get_db_credentials():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ARN)
    secret = json.loads(resp["SecretString"])
    return {
        "host": secret.get("host"),
        "username": secret.get("username"),
        "password": secret.get("password"),
        "port": int(secret.get("port", 5432)),
    }


def upsert_items(conn, items, log):
    with conn.cursor() as cur:

        values = []

        for it in items:
            brand_id = get_or_create_normalized(conn, "brands", it.get("brand"), log)

            images = it.get("images", [])
            if isinstance(images, (dict, list)):
                images = json.dumps(images)

            additional_info = it.get("additional_info", {})
            if isinstance(additional_info, (dict, list)):
                additional_info = json.dumps(additional_info)

            values.append(
                (
                    it.get("code"),
                    it.get("original_id"),
                    it.get("source_url"),
                    it.get("title"),
                    brand_id,
                    it.get("brand"),
                    it.get("scale"),
                    it.get("crawled_date"),
                    it.get("c_ver"),
                    images,
                    additional_info,
                )
            )

        sql = """
        INSERT INTO cars (
            code,
            original_id,
            source_url,
            title,
            brand_id,
            brand,
            scale,
            crawled_date,
            c_ver,
            images,
            additional_info
        )
        VALUES %s
        ON CONFLICT (code)
        DO UPDATE SET
            original_id = EXCLUDED.original_id,
            source_url = EXCLUDED.source_url,
            title = EXCLUDED.title,
            brand_id = EXCLUDED.brand_id,
            brand = EXCLUDED.brand,
            scale = EXCLUDED.scale,
            crawled_date = EXCLUDED.crawled_date,
            c_ver = EXCLUDED.c_ver,
            images = EXCLUDED.images,
            additional_info = EXCLUDED.additional_info
        """

        execute_values(cur, sql, values)
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


################################
def safe_get(url, timeout=15, stream=False):
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout, stream=stream)
    resp.raise_for_status()
    return resp


def download_image_to_s3(img_url, s3_bucket, prefix="images/"):
    resp = safe_get(img_url, stream=True)
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > (10 * 1024 * 1024):
        raise ValueError("Image too large")
    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    parsed = urllib.parse.urlparse(img_url)
    ext = os.path.splitext(parsed.path)[1] or ".jpg"
    key_hash = hashlib.sha1(img_url.encode("utf-8")).hexdigest()
    s3_key = f"{prefix}{key_hash}{ext}"
    s3.upload_fileobj(
        resp.raw, s3_bucket, s3_key, ExtraArgs={"ContentType": content_type}
    )
    return s3_key

def get_lower_ver_rows(conn, version, brand, limit=100):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT source_url, id, images
            FROM cars
            WHERE c_ver < %s AND brand = %s
            ORDER BY c_ver ASC
            LIMIT %s
        """, (version, brand, limit))

        return cur.fetchall()

def get_existing_urls(conn, urls):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT source_url, images FROM cars WHERE source_url = ANY(%s)",
            (urls,)
        )
        return cur.fetchall()

def parse_month_year(date_str):
    for fmt in ("%B %Y", "%b %Y", "%Y"):
        try:
            dt = datetime.datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None

def get_or_create_normalized(conn, table, value, log, brand_id=None):
    if not value:
        return None

    value = value.strip().lower()

    # Create a unique cache key for product_lines since name isn't unique globally
    cache_key = f"{value}_{brand_id}" if table == "product_lines" else value

    if cache_key in NORMALIZATION_CACHE[table]:
        return NORMALIZATION_CACHE[table][cache_key]

    with conn.cursor() as cur:
        if table == "product_lines":
            # Product lines require the brand_id for the unique constraint
            cur.execute(
                f"""
                INSERT INTO {table} (name, brand_id)
                VALUES (%s, %s)
                ON CONFLICT (name, brand_id) 
                DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (value, brand_id)
            )
        else:
            # brands and makes (assuming they only have 'name' constraints)
            cur.execute(
                f"INSERT INTO {table} (name) VALUES (%s) "
                f"ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                f"RETURNING id",
                (value,)
            )

        row_id = cur.fetchone()[0]

    NORMALIZATION_CACHE[table][cache_key] = row_id
    log(f"Resolved {table}: {value}")
    return row_id


def natural_key(url):
    # Extract just filename
    filename = os.path.basename(urlparse(url).path)

    # Split into text and number chunks
    return [
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", filename)
    ]

def crawl_pop_product_page(url, historical_image_urls, log, s3_bucket=S3_BUCKET):
    log(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    title = soup.select_one(".goods-name").get_text()
    rows = soup.select(".goods-main-description p")

    sku = None
    scale = None
    materials = None
    description = rows[1].get_text(separator=" ", strip=True) if rows[1] else None

    # universal way to do it
    container = soup.select_one(".goods-main-description")

    if container:
        text = unicodedata.normalize("NFKC", container.get_text(separator=" ", strip=True))
        match = re.search(r"Product Code\s*[-:]\s*([A-Z0-9-]+)", text)
        if match:
            sku = match.group(1)

    for r in rows:
        r_text = r.get_text(separator=" ", strip=True)
        if r_text and "Scale" in r_text:
            if "1:64" in r_text:
                scale = "1:64"
            elif "1:43" in r_text:
                scale = "1:43"
            elif "1:18" in r_text:
                scale = "1:18"
            elif "1:12" in r_text:
                scale = "1:12"
        elif r_text and "Materials" in r_text:
            materials = r_text.replace("Materials", '', 1)

    if not sku or sku == 'JAN':
        sku = f"PR-{url}"
        log(f"### Crawl Error: {url}, because sku is not found, we are using the url as the sku")

    imgs = soup.select(".goods-img li img")
    img_urls = [img.get("src") for img in imgs if img.get("src")]
    image_s3_key = None
    s3_image_urls = []

    for iu in img_urls:
        if iu in historical_image_urls:
            log(f"Skipping fetching image for {iu}, image already exists")
            continue

        try:
            image_s3_key = download_image_to_s3(iu, s3_bucket)
            image_s3_url = (
                f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
            )
            s3_image_urls.append({"s3_url": image_s3_url, "original_url": iu})
            log(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
        except Exception as e:
            log(f"Failed to download image {iu}: {e}")

    item = {
        "code": f"POP_{sku}",
        "original_id": sku,
        "brand": "poprace",
        "title": title,
        "source_url": url,
        "c_ver": 1,
        "additional_info": {
            "source": url,
            "materials": materials,
            "description": description,
        },
        "source": url,
        "images": s3_image_urls,
        "crawled_date": datetime.datetime.now(datetime.timezone.utc),
        "scale": scale,
    }

    log(f"### Crawled: {sku}, {title}, {scale}, {url}")

    return item

# Lambda handler
def handler(event, context):
    # Detect if this is an API Gateway request
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

    log('Start crawling')

    try:        
        creds = get_db_credentials()
        conn = get_db_conn(creds)
        urls = body.get("product_urls", [])
        override = body.get("override")

        if not urls:
            log("No product urls is given")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "need product urls"}),
            }

        historical_image_urls = []
        if not override: 
            historical_rows = get_existing_urls(conn, urls)

            historical_image_urls = [
                img["original_url"]
                for row in historical_rows
                if row.get("images")
                for img in row["images"]
                if img.get("original_url")
            ]

            historical_urls = [
                row["source_url"]
                for row in historical_rows
                if row.get("source_url")
            ]

            for hu in historical_urls:
                log(
                    f"### Skip Crawling: {hu}, this url is skipped because override mode is OFF"
                )

            print(f'history url {historical_urls}, current url {urls}')

            urls = [
                u for u in urls if u not in historical_urls
            ]
        else:
            log("Override mode is ON, it will erase the existing matching rows and replace with the new crawled data")

        items_to_insert = []
        results = []

        for u in urls:
            try:
                item = crawl_pop_product_page(u, historical_image_urls, log, s3_bucket=S3_BUCKET)
                if (item): 
                    items_to_insert.append(item)

            except Exception as e:
                log(f"Failed crawling {u}: {e}")
                log(traceback.format_exc())
                log(f"### Page not found: {u} does not exist")
                results.append({"url": u, "error": str(e)})

        if len(items_to_insert) > 0:
            upsert_items(conn, items_to_insert, log)

        conn.close()
        log('DONE')

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "crawl completed",
            })
        }

    except Exception as e:
        log(f"Failed to crawl: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
