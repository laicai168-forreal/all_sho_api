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
                    it.get("description_ai"),
                    it.get("make_ai"),
                    it.get("model_ai"),
                    it.get("is_chase"),
                    it.get("is_limited"),
                    it.get("limited_pieces"),
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
            description_ai,
            make_ai,
            model_ai,
            is_chase,
            is_limited,
            limited_pieces,
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
            description_ai = EXCLUDED.description_ai,
            make_ai = EXCLUDED.make_ai,
            model_ai = EXCLUDED.model_ai,
            is_chase = EXCLUDED.is_chase,
            is_limited = EXCLUDED.is_limited,
            limited_pieces = EXCLUDED.limited_pieces,
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


def get_existing_codes(conn, codes):
    if not codes:
        return []

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT code, source_url FROM cars WHERE code = ANY(%s)",
            (codes,)
        )
        return cur.fetchall()


def filter_duplicate_items_for_upsert(conn, items, override, log):
    if not items:
        return []

    filtered_items = []
    seen_codes = set()

    existing_codes = set()
    if not override:
        existing_rows = get_existing_codes(
            conn,
            [item.get("code") for item in items if item.get("code")]
        )
        existing_codes = {
            row["code"]
            for row in existing_rows
            if row.get("code")
        }

    for item in items:
        code = item.get("code")
        source_url = item.get("source_url")

        if not code:
            filtered_items.append(item)
            continue

        if not override and code in existing_codes:
            log(
                f"### Skip Crawling: {source_url}, this item is skipped because code {code} already exists and override mode is OFF"
            )
            continue

        if code in seen_codes:
            log(
                f"### Skip Crawling: {source_url}, this item is skipped because code {code} is duplicated in the current crawl batch"
            )
            continue

        seen_codes.add(code)
        filtered_items.append(item)

    return filtered_items

def parse_month_year(date_str):
    for fmt in ("%B %Y", "%b %Y", "%Y"):
        try:
            dt = datetime.datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def parse_iso_date(date_str):
    if not date_str:
        return None

    try:
        normalized = date_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def normalize_shopify_url(url):
    if not url:
        return None

    if url.startswith("//"):
        return f"https:{url}"

    return urllib.parse.urljoin("https://www.tarmacworks.com", url)


def strip_html_text(value):
    if not value:
        return None

    text = BeautifulSoup(value, "html.parser").get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return "\n".join(lines)


def parse_limited_pieces(text):
    if not text:
        return None

    patterns = [
        r"\b1 of (\d+)\b",
        r"\blimited to (\d+) pieces\b",
        r"\b(\d+) pieces only\b",
        r"\bonly (\d+) pieces\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def infer_scale(*values):
    joined = " ".join([value for value in values if value])
    match = re.search(r"\b(1[/:]\d+)\b", joined)
    if match:
        return match.group(1).replace("/", ":")
    return None


def infer_product_line(title, tags):
    tags = tags or []
    for tag in tags:
        normalized = str(tag).strip()
        if re.fullmatch(r"[A-Z]+(?:43|64)", normalized):
            return normalized.lower()

    if title:
        match = re.search(r"\b([A-Z]+(?:43|64))\b", title)
        if match:
            return match.group(1).lower()

    return None


def extract_make_model_from_title(title):
    if not title:
        return None, None

    normalized = re.sub(r"^\s*1[/:]\d+\s*", "", title).strip()
    model_ai = normalized or None
    primary_segment = normalized.split(" - ")[0].strip() if normalized else ""

    multi_word_makes = [
        "Mercedes-Benz",
        "Mercedes-AMG",
        "Aston Martin",
        "Alfa Romeo",
        "Land Rover",
        "Range Rover",
    ]

    make_ai = None
    for make in multi_word_makes:
        if primary_segment.lower().startswith(make.lower()):
            make_ai = make
            break

    if not make_ai and primary_segment:
        make_ai = primary_segment.split()[0]

    return make_ai, model_ai


def extract_official_product_json(html, source_url=None):
    expected_handle = None
    if source_url:
        parsed_url = urllib.parse.urlparse(source_url)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        if "products" in path_parts:
            product_index = path_parts.index("products")
            if product_index + 1 < len(path_parts):
                expected_handle = path_parts[product_index + 1]

    product_marker = "window.BOLD.common.Shopify.product ="
    product_marker_index = html.find(product_marker)

    if product_marker_index != -1:
        decoder = json.JSONDecoder()
        raw_payload = html[product_marker_index + len(product_marker):].lstrip()

        try:
            product, _ = decoder.raw_decode(raw_payload)
            if isinstance(product, dict):
                if expected_handle and product.get("handle") and product.get("handle") != expected_handle:
                    raise ValueError(
                        f"Shopify product payload handle {product.get('handle')} does not match expected handle {expected_handle}"
                    )
                return product
        except json.JSONDecodeError:
            pass

    marker = "window.BOLD.common.collection ="
    marker_index = html.find(marker)

    if marker_index != -1:
        decoder = json.JSONDecoder()
        raw_payload = html[marker_index + len(marker):].lstrip()

        try:
            products, _ = decoder.raw_decode(raw_payload)
            if isinstance(products, list) and products:
                if expected_handle:
                    for product in products:
                        if isinstance(product, dict) and product.get("handle") == expected_handle:
                            return product
                    available_handles = [
                        product.get("handle")
                        for product in products
                        if isinstance(product, dict) and product.get("handle")
                    ]
                    raise ValueError(
                        f"Expected product handle {expected_handle} was not found in BOLD collection payload. "
                        f"Sample handles: {available_handles[:10]}"
                    )
                return products[0]
        except json.JSONDecodeError:
            pass

    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        raw_json = script.string or script.get_text()
        if not raw_json:
            continue

        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, list):
            candidates = payload
        else:
            candidates = [payload]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") != "Product":
                continue

            offers = candidate.get("offers") or {}
            images = candidate.get("image") or []
            if isinstance(images, str):
                images = [images]

            sku = candidate.get("sku")
            if not sku and isinstance(offers, dict):
                sku = offers.get("sku")

            return {
                "id": candidate.get("productID") or candidate.get("sku") or candidate.get("name"),
                "title": candidate.get("name"),
                "handle": None,
                "description": candidate.get("description"),
                "published_at": None,
                "created_at": None,
                "vendor": candidate.get("brand", {}).get("name") if isinstance(candidate.get("brand"), dict) else candidate.get("brand"),
                "type": None,
                "tags": [],
                "price": None,
                "available": isinstance(offers, dict) and offers.get("availability", "").endswith("InStock"),
                "variants": [{
                    "id": None,
                    "sku": sku,
                    "barcode": candidate.get("gtin13") or candidate.get("gtin12") or candidate.get("mpn"),
                    "available": isinstance(offers, dict) and offers.get("availability", "").endswith("InStock"),
                    "price": None,
                    "compare_at_price": None,
                    "inventory_quantity": None,
                }],
                "images": images,
                "media": [{"src": image_url} for image_url in images],
                "content": candidate.get("description"),
            }

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

    log(f"### Crawled: {sku}, {title}, {scale}, {event}, {notes}, {url}, {item['release_date']}, {product_line}")

    return item


def crawl_tarmac_official_product_page(url, historical_image_urls, log, s3_bucket=S3_BUCKET):
    log(f"Crawling official product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    product = extract_official_product_json(html, source_url=url)

    if not product:
        raise ValueError("Failed to parse official product JSON")

    expected_handle = None
    parsed_url = urllib.parse.urlparse(url)
    path_parts = [part for part in parsed_url.path.split("/") if part]
    if "products" in path_parts:
        product_index = path_parts.index("products")
        if product_index + 1 < len(path_parts):
            expected_handle = path_parts[product_index + 1]

    if expected_handle and product.get("handle") and product.get("handle") != expected_handle:
        raise ValueError(
            f"Parsed official product handle {product.get('handle')} does not match URL handle {expected_handle}"
        )

    title = product.get("title")
    variants = product.get("variants") or []
    primary_variant = variants[0] if variants else {}
    sku = primary_variant.get("sku") or product.get("handle") or str(product.get("id"))
    product_type = product.get("type")
    tags = product.get("tags") or []
    description_html = product.get("description") or product.get("content")
    description_text = strip_html_text(description_html)
    published_at = product.get("published_at")
    created_at = product.get("created_at")
    product_line = infer_product_line(title, tags)
    scale = infer_scale(title, product_type, " ".join(tags))
    make_ai, model_ai = extract_make_model_from_title(title)

    combined_text = " ".join(
        [
            title or "",
            description_text or "",
            " ".join([str(tag) for tag in tags]),
        ]
    )

    is_chase = bool(re.search(r"\bchase\b", combined_text, re.IGNORECASE))
    is_limited = bool(
        re.search(r"\blimited\b", combined_text, re.IGNORECASE)
        or parse_limited_pieces(combined_text) is not None
    )
    limited_pieces = parse_limited_pieces(combined_text)

    price_cents = primary_variant.get("price") or product.get("price")
    compare_at_price_cents = primary_variant.get("compare_at_price") or product.get("compare_at_price")
    image_urls = [
        normalize_shopify_url(image_url)
        for image_url in (product.get("images") or [])
    ]

    media = product.get("media") or []
    for media_item in media:
        image_url = normalize_shopify_url(media_item.get("src"))
        if image_url and image_url not in image_urls:
            image_urls.append(image_url)

    image_urls = [image_url for image_url in image_urls if image_url]

    s3_image_urls = []
    for image_url in image_urls:
        if image_url in historical_image_urls:
            log(f"Skipping fetching image for {image_url}, image already exists")
            continue
        try:
            image_s3_key = download_image_to_s3(image_url, s3_bucket)
            image_s3_url = f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
            s3_image_urls.append({"s3_url": image_s3_url, "original_url": image_url})
            log(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
        except Exception as e:
            log(f"Failed to download image {image_url}: {e}")

    item = {
        "code": f"TW_{sku}",
        "original_id": sku,
        "brand": "tarmacworks",
        "product_line": product_line,
        "title": title,
        "source_url": url,
        "description_ai": description_text,
        "make_ai": make_ai,
        "model_ai": model_ai,
        "is_chase": is_chase,
        "is_limited": is_limited,
        "limited_pieces": limited_pieces,
        "c_ver": 2,
        "additional_info": {
            "source": url,
            "source_type": "official",
            "vendor": product.get("vendor"),
            "handle": product.get("handle"),
            "shopify_product_id": product.get("id"),
            "shopify_variant_id": primary_variant.get("id"),
            "product_type": product_type,
            "tags": tags,
            "barcode": primary_variant.get("barcode"),
            "available": primary_variant.get("available", product.get("available")),
            "inventory_quantity": primary_variant.get("inventory_quantity"),
            "published_at": published_at,
            "created_at": created_at,
            "price": (price_cents / 100) if isinstance(price_cents, int) else None,
            "compare_at_price": (compare_at_price_cents / 100) if isinstance(compare_at_price_cents, int) else None,
            "currency": "USD",
            "description_html": description_html,
        },
        "images": s3_image_urls,
        "release_date": parse_iso_date(published_at) or parse_iso_date(created_at),
        "crawled_date": datetime.datetime.now(datetime.timezone.utc),
        "scale": scale,
    }

    log(
        f"### Crawled: {sku}, {title}, {scale}, {url}, {item['release_date']}, {product_line}, official"
    )

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


def extract_official_product_links_from_catalog(catalog_url, log):
    urls = []
    seen_urls = set()

    log(f"Fetching official catalog page {catalog_url}")
    r = safe_get(catalog_url)
    s = BeautifulSoup(r.text, "html.parser")

    for anchor in s.select('a.product-card__title[href], a[href*="/collections/"][href*="/products/"]'):
        href = anchor.get("href")
        title = anchor.get_text(strip=True)
        if not href:
            continue

        full = normalize_shopify_url(href)
        if not full or "/products/" not in full or full in seen_urls:
            continue

        seen_urls.add(full)
        urls.append({
            "url": full,
            "sku": title,
        })

    log(f"Official url count: {len(urls)}")
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

        elif task_type == 'get_product_url_official':
            catalog_url = body.get("catalog_url")

            if not catalog_url:
                log('No catalog url is found')
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "no catalog url was provided"}),
                }

            log(f'Fetching official product links in {catalog_url}')
            urls = extract_official_product_links_from_catalog(catalog_url, log)

            log(f"Finish getting official tarmac product pages from {catalog_url}")
            log("DONE")

            return {
                "statusCode": 200,
                "headers": cors_headers,
                "body": json.dumps({
                    "message": "official product urls are fetched",
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

                for hu in historical_urls:
                    log(
                        f"### Skip Crawling: {hu}, this url is skipped because override mode is OFF"
                    )

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
                    log(f"### Crawl Error: {u}")
                    results.append({"url": u, "error": str(e)})

            items_to_insert = filter_duplicate_items_for_upsert(conn, items_to_insert, override, log)

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

        elif task_type == 'crawl_official_pages':
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

                urls = [
                    u for u in urls if u not in historical_urls
                ]
            else:
                log("Override mode is ON, it will erase the existing matching rows and replace with the new crawled data")

            items_to_insert = []
            results = []

            for u in urls:
                try:
                    item = crawl_tarmac_official_product_page(u, historical_image_urls, log, s3_bucket=S3_BUCKET)
                    items_to_insert.append(item)
                except Exception as e:
                    log(f"Failed crawling {u}: {e}")
                    log(traceback.format_exc())
                    log(f"### Crawl Error: {u}")
                    if "404" in str(e):
                        log(f"### Page not found: {u} does not exist")
                    results.append({"url": u, "error": str(e)})

            items_to_insert = filter_duplicate_items_for_upsert(conn, items_to_insert, override, log)

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
