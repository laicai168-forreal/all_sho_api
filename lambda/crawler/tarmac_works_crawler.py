import boto3
import botocore
import requests
from io import BytesIO
from bs4 import BeautifulSoup
import time
import hashlib
import datetime
import logging
import os
import urllib.parse
import re
from psycopg2.extras import execute_values, RealDictCursor
import psycopg2
import json
import time
import traceback

# other website for hotwheels
# https://164custom.com/hot-wheels-mainline-case-highlights_HW.html
# https://www.hwtreasure.com/2025-super/

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
            make_id = get_or_create_normalized(conn, "makes", it.get("make"), log)
            product_line_id = get_or_create_normalized(
                conn,
                "product_lines",
                it.get("product_line"),
                log,
                brand_id=brand_id
            )

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
                    make_id,
                    it.get("make"),
                    product_line_id,
                    it.get("scale"),
                    it.get("crawled_date"),
                    it.get("release_date"),
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
            make_id,
            make,
            product_line_id,
            scale,
            crawled_date,
            release_date_approximate,
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
            make_id = EXCLUDED.make_id,
            make = EXCLUDED.make,
            product_line_id = EXCLUDED.product_line_id,
            scale = EXCLUDED.scale,
            crawled_date = EXCLUDED.crawled_date,
            release_date_approximate = EXCLUDED.release_date_approximate,
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

def crawl_tarmac_fandom_product_page(url, historical_image_urls, log, s3_bucket=S3_BUCKET):
    log(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Title / name
    sku = soup.select_one(".mw-page-title-main").get_text()

    if sku.startswith('T43'):
        scale = "1:43"
    else:
        scale = "1:64"

    rows = soup.select(".mw-content-ltr table tr")
    title = None
    product_line = None
    release_time = None
    event = None
    notes = None
    main_image = None

    # One type of page, that has smaller amout of data
    if len(rows) == 2:
        # the table layout may varies T_T
        header_cells = rows[0].select("td")
        cells = rows[1].select("td")
        for idx, hc in enumerate(header_cells):
            header_cell_text = hc.select_one("font b").get_text() if hc.select_one("font b") else None
            if header_cell_text == "Description":
                title = cells[idx].get_text() if cells[idx] else None
            if header_cell_text == "Date":
                release_time = cells[idx].select_one("a").get_text(strip=True) if cells[idx].select_one("a") else None
            if header_cell_text == "Series":
                product_line = cells[idx].select_one("a").get_text(strip=True).lower() if cells[idx].select_one("a") else None
            if header_cell_text == "Event":
                event = cells[idx].select_one("a").get_text(strip=True) if cells[idx].select_one("a") else None

    else:
        title = rows[1].select_one("td").get_text()
        for r in rows[2:6]:
            # some of the page may have less row because it is missing the event row
            first_text = (
                r.select("td")[0].select_one("font b").get_text()
                if r and r.select("td")[0]
                else None
            )
            if first_text and first_text == "Date":
                release_time = r.select("td")[1].get_text()
            if first_text and first_text == "Series":
                product_line = r.select("td")[1].get_text()
            if first_text and first_text == "Event":
                event = r.select("td")[1].get_text()
            if first_text and first_text == "Notes":
                notes = r.select("td")[1].get_text()
        main_image = soup.select_one(".mw-content-ltr .mw-halign-left a")

    imgs = soup.select('.mw-content-ltr div span[typeof="mw:File"] a')
    extra_imgs = soup.select('.mw-content-ltr p span[typeof="mw:File"] a')
    imgs.extend(extra_imgs)
    image_s3_key = None
    s3_image_urls = []

    # for the second type of page, the main image is in a different wrapper
    if main_image:
        imgs.insert(0, main_image)

    for i in imgs:
        if i and i.get("href"):
            u = i.get("href")
            if u in historical_image_urls:
                log(f"Skipping fetching image for {u}, image already exists")
                continue
            try:
                image_s3_key = download_image_to_s3(u, s3_bucket)
                image_s3_url = (
                    f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
                )
                s3_image_urls.append({"s3_url": image_s3_url, "original_url": u})
                log(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
            except Exception as e:
                log(f"Failed to download image {u}: {e}")

    item = {
        "code": f"TW_{sku}",
        "original_id": sku,
        "brand": "tarmacworks",
        "product_line": product_line,
        "title": title,
        "source_url": url,
        "c_ver": 1,
        "additional_info": {
            "source": url,
            "event": event,
            "notes": notes,
        },
        "source": url,
        "images": s3_image_urls,
        "release_date": parse_month_year(release_time),
        "crawled_date": datetime.datetime.now(datetime.timezone.utc),
        "scale": scale,
    }

    log(f"### Crawled: {sku}, {title}, {scale}, {event}, {notes}, {url}, {item["release_date"]}, {product_line}")

    return item


def extract_product_links_from_catalog(catalog_url, log):
    urls = []
    log(f"Fetching catalog page {catalog_url}")
    r = safe_get(catalog_url)
    s = BeautifulSoup(r.text, "html.parser")

    image_catalog_links = s.select('.mw-content-ltr div span[typeof="mw:File"] a')

    if image_catalog_links and len(image_catalog_links) > 0:
        for a in image_catalog_links:
            href = a.get("href")
            sku = a.get("title")
            if href:
                full = urllib.parse.urljoin("https://tarmacworks.fandom.com", href)
                urls.append({
                    "url": full,
                    "sku": sku,
                })

    else:
        # otherwise it is the table catalog
        rows = s.select(".mw-content-ltr .wikitable tr")

        if rows and len(rows) > 0:
            #frist row is the header
            for r in rows[1:]:
                cells = r.select('td')
                last_cell_text = cells[-1].get_text() if cells[-1] else None
                if "Event" in last_cell_text:
                    log(f"!!! Found event {last_cell_text}")
                    continue
                #initiate the anchor
                a = cells[-1].select_one("a") if cells[-1] else None

                if not a: 
                    continue
                else:
                    href = a.get("href") if a else None
                    sku = a.get("title") if a else None
                    if href:
                        full = urllib.parse.urljoin("https://tarmacworks.fandom.com", href)
                        urls.append(
                            {
                                "url": full,
                                "sku": sku,
                            }
                        )
        log(f"Url Count: {len(urls)}")

    return urls

# Lambda handler
def handler(event, context):
    # Detect if this is an API Gateway request
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])
    else:
        body = event

    task_type = body.get("task_type")
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
        version = body.get("version")

        if task_type == 'get_product_url':
            catalog_url = body.get("catalog_url")

            if not catalog_url:
                log('No catalog url is found')
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "no catalog url was provided"}),
                }

            log(f'Fetching product links in {catalog_url}')
            urls = extract_product_links_from_catalog(catalog_url, log)

            log(f"Finish getting tarmac product pages from {catalog_url}")
            log(f"DONE")

            return {
                "statusCode": 200,
                "headers": cors_headers,
                "body": json.dumps({
                    "message": "product urls are fetched",
                    "product_urls": urls,
                    "count": len(urls),
                })
            }

        elif task_type ==  'crawl_fandom_pages':        
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
                    item = crawl_tarmac_fandom_product_page(u, historical_image_urls, log, s3_bucket=S3_BUCKET)
                    items_to_insert.append(item)

                    print(f"""
                        {len(body.get("product_urls", []))} given urls.
                        {len(urls)} new urls
                    """)

                except Exception as e:
                    log(f"Failed crawling {u}: {e}")
                    log(traceback.format_exc())
                    results.append({"url": u, "error": str(e)})

            if len(items_to_insert) > 0:
                upsert_items(conn, items_to_insert, log)

            conn.close()
            log('DONE')

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "crawl completed",
                    "version": version,
                })
            }
        else:
            log(f"Failed to crawl: no task type specified")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "no task type specified"})
            }

    except Exception as e:
        log(f"Failed to crawl: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
