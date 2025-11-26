import boto3
import botocore
import requests
from io import BytesIO
from PIL import Image
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

# other website for hotwheels
# https://164custom.com/hot-wheels-mainline-case-highlights_HW.html
# https://www.hwtreasure.com/2025-super/

# CONFIG via env vars
S3_BUCKET = os.environ.get("BUCKET_NAME", "DiecastDataBucket")
DDB_TABLE = os.environ.get("TABLE_NAME", "DiecastCarsTable")
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
USER_AGENT = os.environ.get("USER_AGENT", "CarCrawler/1.0 Python/requests")
region = os.environ.get("AWS_REGION", "us-east-1")

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.5"))

# AWS clients
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
table = dynamodb.Table(DDB_TABLE)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

urls = {
    "tarmac": os.getenv("TARMAC_URL"),
    "minigt": os.getenv("MINIGT_URL"),
    "inno64": os.getenv("INNO64_URL"),
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


def upsert_items(conn, items):
    with conn.cursor() as cur:
        sql = """
        INSERT INTO cars (id, original_id, source_url, title, brand, make, scale, crawled_date, c_ver, images, additional_info)
        VALUES %s
        ON CONFLICT (id)
        DO UPDATE SET
          original_id = EXCLUDED.original_id,
          source_url = EXCLUDED.source_url,
          title = EXCLUDED.title,
          brand = EXCLUDED.brand,
          make = EXCLUDED.make,
          scale = EXCLUDED.scale,
          crawled_date = EXCLUDED.crawled_date,
          c_ver = EXCLUDED.c_ver,
          images = EXCLUDED.images,
          additional_info = EXCLUDED.additional_info;
        """

        values = []
        for it in items:
            images = it.get("images", [])
            if isinstance(images, (dict, list)):
                images = json.dumps(images)

            additional_info = it.get("additional_info", {})
            if isinstance(additional_info, (dict, list)):
                additional_info = json.dumps(additional_info)

            values.append(
                (
                    it.get("id"),
                    it.get("original_id"),
                    it.get("source_url"),
                    it.get("title"),
                    it.get("brand"),
                    it.get("make"),
                    it.get("scale"),
                    it.get("crawled_date"),
                    it.get("c_ver"),
                    images,
                    additional_info,
                )
            )

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


##################################
def safe_get(url, timeout=15, stream=False):
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout, stream=stream)
    resp.raise_for_status()
    return resp


def slugify(text):
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text


def page_id_from_url(url):
    canonical = urllib.parse.urljoin(url, urllib.parse.urlparse(url).path)
    return "minigt:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def get_current_row(conn, id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT images FROM cars WHERE id = %s", (id,))
        existing = cur.fetchone()

    return existing

def get_minigt_og_image(soup, base_url):
    imgs = soup.select(".pro_wrap-d .product_box img")
    img_urls = []
    if imgs and len(imgs) > 0:
        for i in imgs:
            if i.get("src"):
                img_urls.append(urllib.parse.urljoin(base_url, i.get("src")))
    return img_urls


def parse_product_details(soup):
    """
    Extract key/value details: SKU, scale, release date, color, variant, etc.
    Needs adapting based on actual page layout.
    """
    data = {}
    # For example, maybe there's a section with .product-info or table
    info_section = soup.select_one(".info-list")
    if info_section:
        # either rows or label-value pairs
        # Try table
        for row in info_section.select("li"):
            span = row.find("span")
            if span:
                k = row.find(text=True, recursive=False).get_text(strip=True)
                v = " ".join(span.stripped_strings)
                if k == "Item No.":
                    data["id"] = v
                else:
                    data[k] = v
        # TODO: delete this if needed, or divs (label / value pairs)
        # for label in info_section.select(".label, .spec-label"):
        #     val = label.find_next_sibling(".value")
        #     if val:
        #         k = label.get_text(strip=True)
        #         v = " ".join(val.stripped_strings)
        #         data[k] = v
    return data


def extract_summary(soup):
    # maybe a product description paragraph
    desc = soup.select_one(".des .edit-box p")
    if desc:
        return desc.get_text(strip=True)
    # TODO: may not need the following
    # fallback: first non-empty paragraph
    for p in soup.select("p"):
        text = p.get_text(strip=True)
        if text:
            return text
    return ""


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



def crawl_minigt_product_page(url, historical_image_urls, version, s3_bucket=S3_BUCKET):
    logger.info(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Title / name
    title_tag = soup.select_one(".pro-name p")
    title = (
        title_tag.get_text(strip=True)
        if title_tag
        else urllib.parse.urlparse(url).path.split("/")[-1]
    )

    details = parse_product_details(soup)

    image_urls = get_minigt_og_image(soup, url)
    images = []

    for u in image_urls:
        print(f'checking image url {u}')
        if u in historical_image_urls:
            logger.info(f"Skipping fetching image for {u}, image already exists")
            continue
        try:
            image_s3_key = download_image_to_s3(u, s3_bucket)
            image_s3_url = (
                f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
            )
            images.append({"s3_url": image_s3_url, "original_url": u})
            logger.info(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
        except Exception as e:
            logger.warning(f"Failed to download image {u}: {e}")

    item = {
        "id": f"MGT_{details["id"]}",
        "original_id": details["id"],
        "brand": "minigt",
        "make": details["Marque"],
        "title": title,
        "source_url": url,
        "c_ver": version,
        "additional_info": {
            "source": url,
        },
        "source": url,
        "images": images,
        "crawled_date": datetime.datetime.now(datetime.timezone.utc),
        "scale": "1:64",
    }

    return item


def extract_minigt_links_from_catalog(catalog_url, booked_urls, max_pages=100):
    urls = set()
    ## keeping this version that considers pagination, may not need it later.
    # next_url = catalog_url
    # while next_url and len(urls) < max_pages:
    #     logger.info(f"Fetching catalog page {next_url}")
    #     time.sleep(REQUEST_DELAY)
    #     r = safe_get(next_url)
    #     s = BeautifulSoup(r.text, "html.parser")

    #     # change this selector to match links to individual products
    #     for a in s.select(".product_box a"):
    #         href = a.get("href")
    #         if href:
    #             full = urllib.parse.urljoin(next_url, href)
    #             if full not in booked_urls: 
    #                 urls.add(full)
    #                 if len(urls) >= max_pages:
    #                     break

    #     # pagination or “next page”
    #     next_btn = s.select(".cdp_i")[-1]
    #     next_btn = s.select(".cdp_i")[-1]
    #     if next_btn and next_btn.get("href"):
    #         next_url = urllib.parse.urljoin(next_url, next_btn.get("href"))
    #     else:
    #         next_url = None

    logger.info(f"Fetching catalog page {catalog_url}")
    time.sleep(REQUEST_DELAY)
    r = safe_get(catalog_url)
    s = BeautifulSoup(r.text, "html.parser")

    # change this selector to match links to individual products
    for a in s.select(".product_box a"):
        href = a.get("href")
        if href:
            full = urllib.parse.urljoin(catalog_url, href)
            if full not in booked_urls: 
                urls.add(full)
                if len(urls) >= max_pages:
                    break

    return list(urls)


# Hot wheels page is consisting multiple items
def crawl_hotwheels_product_page(url, s3_bucket=S3_BUCKET, ddb_table=table):
    logger.info(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Title / name
    title = soup.select_one(".mw-page-title-main").get_text()
    rows = soup.select(".wikitable.sortable tbody tr")
    items = []

    for row in rows:
        cells = row.find_all("td")
        img_url = None
        image_s3_url = None

        if len(cells) >= 13:
            color = cells[3].get_text()
            id = cells[9].get_text(strip=True)
            img = cells[12].find("a")
            release_year = cells[1].get_text()
            image_s3_key = None

            if img and img.get("href"):
                img_url = img.get("href")
                try:
                    image_s3_key = download_image_to_s3(img_url, s3_bucket)
                    image_s3_url = (
                        f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
                    )
                    logger.info(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
                except Exception as e:
                    logger.warning(f"Failed to download image {img_url}: {e}")

            item = {
                "id": id,
                "brand": "hotwheels",
                "make": "",
                "title": f"{title}, {color}, released in {release_year}",
                "additional_info": {},
                "image_url": image_s3_url or "",
                "crawled_date": datetime.datetime.utcnow().isoformat() + "Z",
                "scale": "1:64",
            }

            items.append(item)

        else:
            logger.info("Not enough cells for all information")
    return items


def extract_hotwheels_links_from_catalog(catalog_url, max_pages=100):
    urls = set()
    while catalog_url and len(urls) < max_pages:
        logger.info(f"Fetching catalog page {catalog_url}")
        time.sleep(REQUEST_DELAY)
        r = safe_get(catalog_url)
        s = BeautifulSoup(r.text, "html.parser")

        # change this selector to match links to individual products
        for a in s.select(".sortable.wikitable tr td:nth-child(3) a"):
            href = a.get("href")
            if href:
                full = urllib.parse.urljoin("https://hotwheels.fandom.com/wiki", href)
                urls.add(full)
                if len(urls) >= max_pages:
                    break

    return list(urls)


# 164 custom Hot wheels page is consisting multiple items
def crawl_hotwheels_164custom_product_page(url, historical_image_urls, version, s3_bucket=S3_BUCKET):
    logger.info(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one(".table")
    rows = table.select("tbody tr")

    year_cell = rows[0].select("td")[1]
    year = year_cell.get_text(strip=True) if year_cell is not None else ""

    id_cell = rows[1].select("td")[1]
    id = id_cell.get_text(strip=True) if id_cell is not None else ""

    hw_no_cell = rows[2].select("td")[1]
    hw_no = hw_no_cell.get_text(strip=True) if hw_no_cell is not None else ""

    type_cell = rows[3].select("td")[1]
    type = type_cell.get_text(strip=True) if type_cell is not None else ""

    name_cell = rows[4].select("td")[1]
    name = name_cell.get_text(strip=True) if name_cell is not None else ""

    color_cell = rows[5].select("td")[1]
    color = color_cell.get_text(strip=True) if color_cell is not None else ""

    series_name_cell = rows[6].select("td")[1]
    series_name = (
        series_name_cell.get_text(strip=True) if series_name_cell is not None else ""
    )

    series_no_cell = rows[7].select("td")[1]
    series_no = (
        series_no_cell.get_text(strip=True) if series_no_cell is not None else ""
    )

    case_cell = rows[9].select("td")[1]
    case = case_cell.get_text(strip=True) if case_cell is not None else ""

    imgs = soup.select(".gallery-img a")

    images = []

    if imgs:
        for i in imgs:
            img_url = i.get("href")
            print(f'checking image url {img_url}')
            print(f'historical_image_urls {historical_image_urls}')
            if img_url in historical_image_urls:
                logger.info(f"Skipping fetching image of {img_url}")
                continue
            if img_url:
                try:
                    image_s3_key = download_image_to_s3(img_url, s3_bucket)
                    image_s3_url = (
                        f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
                    )
                    images.append({"s3_url": image_s3_url, "original_url": img_url})
                    logger.info(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
                except Exception as e:
                    logger.warning(f"Failed to download image {img_url}: {e}")
            else:
                logger.warning(f"There is no url for the img of {url}")
    else:
        logger.warning(
            f"There is no images for hot wheels {url}, check if the dom still exists"
        )

    item = {
        "id": f"HW_{id}",
        "original_id": id,
        "brand": "hotwheels",
        "make": "",
        "title": name,
        "c_ver": version,
        "source_url": url,
        "additional_info": {
            "case": case,
            "series_no": series_no,
            "series_name": series_name,
            "type": type,
            "hw_no": hw_no,
            "source": url,
            "color": color,
        },
        "images": images or [],
        "crawled_date": datetime.datetime.now(datetime.timezone.utc),
        "scale": "1:64",
    }

    return item


def extract_hotwheels_164custom_links_from_catalog(catalog_url, max_pages=100):
    urls = set()
    logger.info(f"Fetching catalog page {catalog_url}")
    time.sleep(REQUEST_DELAY)
    r = safe_get(catalog_url)
    s = BeautifulSoup(r.text, "html.parser")
    rows = s.select("table tbody tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        a_tag = cells[2].find("a")
        if not a_tag:
            continue
        href = a_tag.get("href")
        if href:
            urls.add(href)
        if len(urls) >= max_pages:
            break

    return list(urls)


# Lambda handler
def handler(event, context):
    version = event.get("version")
    brand = event.get("brand")
    default_limit = 0
    max_pages = event.get("max_pages", default_limit)
    known_brands = ['minigt', 'hotwheels']
    if not version or version == 0:
        return {
                "statusCode": 500,
                "body": json.dumps({"error": 'no version is specified, version should not be 0, you need to in put a version'}),
            }
    if not brand:
        return {
                "statusCode": 500,
                "body": json.dumps({"error": 'no brand specified, you need to input a brand name'}),
            }
    
    if brand not in known_brands:
        return {
                "statusCode": 500,
                "body": json.dumps({"error": f'brand name you give does not exist, use those ones {', '.join(known_brands)}'}),
            }
    
    if not max_pages:
        logger.info(f'no limit is given, setting it to default {default_limit}')
    
    creds = get_db_credentials()
    conn = get_db_conn(creds)
    urls = event.get("product_urls", [])
    # lower_version_rows = get_lower_ver_rows(conn, version, brand, max_pages)
    # print(f'lower_versoin_rows {lower_version_rows}')
    # urls.extend([row.get("source_url") for row in lower_version_rows if row.get("source_url")])
    # # get this list of downloaded images urls, so we will skip the dup download operations to these images
    # historical_image_urls = [
    #     img["original_url"]
    #     for row in lower_version_rows
    #     if row.get("images")
    #     for img in row["images"]
    #     if img.get("original_url")
    # ]
    # print(f'historical images: {historical_image_urls}')
    
    if "catalog_url" in event and "brand" in event and len(urls) < max_pages:
        try:
            if event.get("brand") == "minigt":
                urls.extend(extract_minigt_links_from_catalog(
                    event["catalog_url"], urls, max_pages=max_pages
                ))
            # if event.get("brand") == "hotwheels":
            #     urls = extract_hotwheels_links_from_catalog(
            #         event["catalog_url"], max_pages=max_pages
            #     )
            if event.get("brand") == "hotwheels":
                urls.extend(extract_hotwheels_164custom_links_from_catalog(
                    event["catalog_url"], max_pages=max_pages
                ))
        except Exception as e:
            logger.exception(f"Failed to extract from catalog: {e}")
            return {"error": str(e)}
    
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

    items_to_insert = []
    results = []
    
    for u in urls:
        try:
            if brand == "minigt":
                item = crawl_minigt_product_page(u, historical_image_urls, version)
                items_to_insert.append(item)

            # elif brand == "hotwheels":
            #     items = crawl_hotwheels_product_page(u)
            #     items_to_insert.extend(items)

            elif brand == "hotwheels":
                item = crawl_hotwheels_164custom_product_page(u, historical_image_urls, version)
                items_to_insert.append(item)
                # return {"count": len(items_to_insert), "results": items_to_insert}
            else:
                logger.exception("no brand specified")
            
            print(f"""
                {len(event.get("product_urls", []))} given urls.
                {len(urls)} new urls
            """)

        except Exception as e:
            logger.exception(f"Failed crawling {u}: {e}")
            results.append({"url": u, "error": str(e)})
    if len(items_to_insert) > 0:
        upsert_items(conn, items_to_insert)

    conn.close()


# If run locally
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Crawl diecast product pages to AWS")
    parser.add_argument("--catalog", help="Catalog URL to crawl from")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument(
        "--product-urls", nargs="*", help="Specific product pages to crawl"
    )
    parser.add_argument(
        "--version", help="Specific version"
    )
    parser.add_argument(
        "--brand", help="Specific brand"
    )
    args = parser.parse_args()
    event = {}
    if args.product_urls:
        event["product_urls"] = args.product_urls
        event["brand"] = args.brand
        event["version"] = args.version
    if args.catalog:
        event["catalog_url"] = args.catalog
        event["max_pages"] = args.max_pages
        event["brand"] = args.brand
        event["version"] = args.version
    out = handler(event, None)
    print(json.dumps(out, indent=2))
