import boto3
import botocore
import requests
from bs4 import BeautifulSoup
import time
import hashlib
import datetime
import logging
import os
import urllib.parse
import re
from psycopg2.extras import execute_values
import psycopg2

# CONFIG via env vars
S3_BUCKET = os.environ.get("BUCKET_NAME", "DiecastDataBucket")
DDB_TABLE = os.environ.get("TABLE_NAME", "DiecastCarsTable")
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
USER_AGENT = os.environ.get(
    "USER_AGENT", "CarCrawler/1.0 Python/requests"
)
region = os.environ.get("AWS_REGION", "us-east-1")

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.5"))

# AWS clients
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client('secretsmanager')
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
    secret = json.loads(resp['SecretString'])
    return {
        'host': secret.get('host'),       # ensure your Secret contains host info
        'username': secret.get('username'),
        'password': secret.get('password'),
        'port': int(secret.get('port', 5432))
    }

def upsert_items(conn, items):
    with conn.cursor() as cur:
        sql = """
        INSERT INTO hotwheels_items (fandom_id, title, release_year, manufacturer, series, image_url, raw_html_s3_key, updated_at)
        VALUES %s
        ON CONFLICT (fandom_id)
        DO UPDATE SET
          title = EXCLUDED.title,
          release_year = EXCLUDED.release_year,
          manufacturer = EXCLUDED.manufacturer,
          series = EXCLUDED.series,
          image_url = EXCLUDED.image_url,
          raw_html_s3_key = EXCLUDED.raw_html_s3_key,
          updated_at = now()
        RETURNING id;
        """
        values = [
            (
                it.get('fandom_id'),
                it.get('title'),
                it.get('release_year'),
                it.get('manufacturer'),
                it.get('series'),
                it.get('image_url'),
                it.get('raw_html_s3_key')
            ) for it in items
        ]
        execute_values(cur, sql, values)
        conn.commit()

def get_db_conn(creds):
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=creds['username'],
        password=creds['password'],
        host=creds['host'],
        port=creds['port']
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


def get_minigt_og_image(soup, base_url):
    # og = soup.find("meta", property="og:image")
    # if og and og.get("content"):
    #     return urllib.parse.urljoin(base_url, og.get("content"))
    # fallback: a main product image, maybe class “product-image” or gallery main
    img = soup.select_one(
        ".pro_wrap-d .product_box img"
    )
    if img and img.get("src"):
        return urllib.parse.urljoin(base_url, img.get("src"))
    return None


def parse_product_details(soup):
    """
    Extract key/value details: SKU, scale, release date, color, variant, etc.
    Needs adapting based on actual page layout.
    """
    data = {}
    # For example, maybe there's a section with .product-info or table
    info_section = soup.select_one(
        ".info-list"
    )
    if info_section:
        # either rows or label-value pairs
        # Try table
        for row in info_section.select("li"):
            span = row.find("span")
            if span:
                k = row.find(text=True, recursive=False).get_text(strip=True)
                v = " ".join(span.stripped_strings)
                if k == "Item No.":
                    data['id'] = v
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


def crawl_minigt_product_page(url, s3_bucket=S3_BUCKET, ddb_table=table):
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
    slug = slugify(title)
    pid = page_id_from_url(url)

    image_url = get_minigt_og_image(soup, url)
    
    image_s3_key = None
    if image_url:
        try:
            image_s3_key = download_image_to_s3(image_url, s3_bucket)
            logger.info(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
        except Exception as e:
            logger.warning(f"Failed to download image {image_url}: {e}")
            image_s3_key = None

    details = parse_product_details(soup)
    summary = extract_summary(soup)
    image_s3_url = f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"

    item = {
        "id": details['id'],
        "brand": 'minigt',
        "page_id": pid,
        "title": title,
        "slug": slug,
        "product_url": url,
        "image_url": image_url or "",
        "image_s3_key": image_s3_key or "",
        "image_s3_url": image_s3_url,
        "marque": details['Marque'],
        "scale": details['Scale'],
        "status": details['Status'],
        "summary": summary,
        "last_crawled": datetime.datetime.utcnow().isoformat() + "Z",
    }

    # maybe capture first part of raw html snippet for debugging
    snippet = soup.select_one(".pd-list-a")
    if snippet:
        snippet_text = snippet.encode_contents()[:2000]
        try:
            item["raw_html_snippet"] = snippet_text.decode("utf-8", errors="ignore")
        except:
            item["raw_html_snippet"] = ""

    ddb_table.put_item(Item=item)
    logger.info(f"Saved metadata for {pid}")

    return item


def extract_minigt_links_from_catalog(catalog_url, max_pages=100):
    urls = set()
    next_url = catalog_url
    while next_url and len(urls) < max_pages:
        logger.info(f"Fetching catalog page {next_url}")
        time.sleep(REQUEST_DELAY)
        r = safe_get(next_url)
        s = BeautifulSoup(r.text, "html.parser")

        # change this selector to match links to individual products
        for a in s.select(
            ".product_box a"
        ):
            href = a.get("href")
            if href:
                full = urllib.parse.urljoin(next_url, href)
                urls.add(full)
                if len(urls) >= max_pages:
                    break

        # pagination or “next page”
        next_btn = s.select(".cdp_i")[-1]
        if next_btn and next_btn.get("href"):
            next_url = urllib.parse.urljoin(next_url, next_btn.get("href"))
        else:
            next_url = None

    return list(urls)

# Hot wheels page is consisting multiple items
def crawl_hotwheels_product_page(url, s3_bucket=S3_BUCKET, ddb_table=table):
    logger.info(f"Crawling product {url}")
    time.sleep(REQUEST_DELAY)
    resp = safe_get(url)
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Title / name
    title = soup.select_one(".mw-page-title-main span").get_text
    rows = soup.select(".wikitable.sortable tbody tr")
    items = []

    for row in rows:
        cells = row.find_all("td")
        img_url = None
        image_s3_url = None

        if len(cells) >= 13:
            color = cells[3].get_text()
            id = cells[9].get_text(strip=True)
            img = cells[12].find("img")
            release_year = cells[1].get_text()
            image_s3_key = None
            
            if img and img.get("data-src"):
                img_url = img.get("data-src")
                try:
                    image_s3_key = download_image_to_s3(img_url, s3_bucket)
                    image_s3_url = f"https://{s3_bucket}.s3.{region}.amazonaws.com/{image_s3_key}"
                    logger.info(f"Downloaded image to s3://{s3_bucket}/{image_s3_key}")
                except Exception as e:
                    logger.warning(f"Failed to download image {img_url}: {e}")
            
            item = {
                "id": id,
                "brand": 'hotwheels',
                "title": f"{title}, {color}, released in {release_year}",
                "image_s3_url": image_s3_url,
                "image_s3_key": image_s3_key or "",
                "last_crawled": datetime.datetime.utcnow().isoformat() + "Z",
                "release": release_year,
                "scale": "1:64",
            }

            items.append(item)

            # ddb_table.put_item(Item=item)
            # logger.info(f"Saved metadata for {id}, {title}")

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
        for a in s.select(
            ".sortable.wikitable tr td:nth-child(3) a"
        ):
            href = a.get("href")
            if href:
                full = urllib.parse.urljoin("https://hotwheels.fandom.com/wiki", href)
                urls.add(full)
                if len(urls) >= max_pages:
                    break

    return list(urls)



# Lambda handler
def handler(event, context):
    creds = get_db_credentials()
    conn = get_db_conn(creds)
    urls = event.get("product_urls", [])
    if "catalog_url" and "brand" in event and not urls:
        max_pages = event.get("max_pages", 100)
        try:
            if event.get("brand") == "minigt":
                urls = extract_minigt_links_from_catalog(event["catalog_url"], max_pages=max_pages)
            if event.get("brand") == "hotwheels":
                urls = extract_hotwheels_links_from_catalog(event["catalog_url"], max_pages=max_pages)
        except Exception as e:
            logger.exception(f"Failed to extract from catalog: {e}")
            return {"error": str(e)}

    items_to_insert = []
    results = []
    for u in urls:
        try:
            if event.get("brand") == "minigt":
                it = crawl_minigt_product_page(u)
                results.append({"page_id": it["page_id"], "title": it["title"], "url": u})
                return {"count": len(results), "results": results}
            if event.get("brand") == "hotwheels":
                items = crawl_hotwheels_product_page(u)
                results.extend(items)
                return {"count": len(results), "results": results}
            else:
                logger.exception("no brand specified")

        except Exception as e:
            logger.exception(f"Failed crawling {u}: {e}")
            results.append({"url": u, "error": str(e)})
    if items_to_insert:
        upsert_items(conn, items_to_insert)
        logger.info("Upserted %d items", len(items_to_insert))
        
    conn.close()

    


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
