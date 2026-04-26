import datetime
import hashlib
import json
import logging
import os
import re
import time
import traceback
import urllib.parse
import uuid

import boto3
import psycopg2
import requests
from bs4 import BeautifulSoup
from requests import HTTPError
from psycopg2.extras import Json, execute_values


S3_BUCKET = os.environ.get("BUCKET_NAME", "DiecastDataBucket")
SECRET_ARN = os.environ.get("DB_SECRET_ARN", "SECRET")
DB_NAME = os.environ.get("DB_NAME", "DB")
USER_AGENT = os.environ.get(
    "USER_AGENT",
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
)
LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE_NAME", "CrawlerLogsTable")

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.0"))
RAW_HTML_PREFIX = os.environ.get("HOTWHEELS_RAW_HTML_PREFIX", "hotwheels/raw-html/")
PARSER_VERSION = "2026-04-25-v2"
SKIPPED_CATEGORY_PAGE_TITLES = {
    "List of 1968 Hot Wheels",
    "List of 1968 Hot Wheels new castings",
    "List of Sets and Cases",
}

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
log_table = dynamodb.Table(LOGS_TABLE_NAME)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
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


def get_db_conn(creds):
    return psycopg2.connect(
        dbname=DB_NAME,
        user=creds["username"],
        password=creds["password"],
        host=creds["host"],
        port=creds["port"],
    )


def safe_get(url, timeout=20):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://hotwheels.fandom.com/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def extract_fandom_page_name(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if "/wiki/" not in path:
        return None

    return urllib.parse.unquote(path.split("/wiki/", 1)[1]).strip()


def build_fandom_page_url(base_url, page_title):
    parsed = urllib.parse.urlparse(base_url)
    encoded_title = urllib.parse.quote(page_title.replace(" ", "_"), safe=":_-()'")
    return f"{parsed.scheme}://{parsed.netloc}/wiki/{encoded_title}"


def is_category_page_name(page_name):
    return bool(page_name and page_name.startswith("Category:"))


def should_skip_category_member_title(title):
    return normalize_space(title) in SKIPPED_CATEGORY_PAGE_TITLES


def fetch_fandom_page_html_via_api(url, timeout=20):
    page_name = extract_fandom_page_name(url)
    if not page_name:
        raise ValueError("Could not determine fandom page name from URL")

    parsed = urllib.parse.urlparse(url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/api.php"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }
    params = {
        "action": "parse",
        "page": page_name,
        "prop": "text|displaytitle",
        "format": "json",
        "formatversion": "2",
    }

    resp = requests.get(api_url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    parsed_page = payload.get("parse") or {}
    html = parsed_page.get("text")
    title = parsed_page.get("displaytitle") or page_name.replace("_", " ")

    if not html:
        raise ValueError("Fandom API returned no parsed HTML")

    return html, normalize_space(BeautifulSoup(title, "html.parser").get_text(" ", strip=True))


def fetch_fandom_api_json(url, params, timeout=20):
    parsed = urllib.parse.urlparse(url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/api.php"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }
    resp = requests.get(api_url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def normalize_space(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_header(value):
    text = normalize_space(value).lower()
    text = text.replace("#", " number ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def upload_raw_html(url, html):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or parsed.netloc
    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()
    file_stub = re.sub(r"[^a-zA-Z0-9_-]+", "-", path.strip("/")) or "page"
    key = f"{RAW_HTML_PREFIX}{file_stub}-{url_hash}.html"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
    )
    return key


def get_page_title(soup, fallback_title=None):
    if fallback_title:
        return normalize_space(fallback_title)

    title = soup.select_one(".page-header__title")
    if title:
        return normalize_space(title.get_text(" ", strip=True))

    heading = soup.find("h1")
    if heading:
        return normalize_space(heading.get_text(" ", strip=True))

    if soup.title:
        return normalize_space(soup.title.get_text(" ", strip=True))

    return ""


def extract_table(table):
    headers = []
    header_row = table.find("tr")
    if not header_row:
        return [], []

    headers = [
        normalize_header(cell.get_text(" ", strip=True))
        for cell in header_row.find_all(["th", "td"])
    ]

    rows = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        values = [normalize_space(cell.get_text(" ", strip=True)) for cell in cells]
        if not any(values):
            continue

        row_map = {}
        extra_values = []
        for index, value in enumerate(values):
            if index < len(headers):
                row_map[headers[index]] = value
            else:
                extra_values.append(value)

        if extra_values:
            row_map["_extra"] = extra_values

        rows.append(row_map)

    return headers, rows


def extract_section_heading(table):
    current = table
    while current:
        current = current.find_previous_sibling()
        if current is None:
            break

        if current.name in {"h2", "h3", "h4"}:
            headline = current.select_one(".mw-headline")
            text = headline.get_text(" ", strip=True) if headline else current.get_text(" ", strip=True)
            text = normalize_space(text)
            if text and text.lower() not in {"contents", "see also", "references"}:
                return text

    return None


def is_year_list_page(page_title):
    return bool(re.match(r"^List of \d{4} Hot Wheels$", page_title))


def extract_year_from_title(page_title):
    match = re.search(r"(\d{4})", page_title or "")
    if not match:
        return None
    return int(match.group(1))


def parse_optional_year(value):
    if not value:
        return None

    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    if not match:
        return None

    return int(match.group(0))


def _clean_stage_sku(value):
    if value is None:
        return None

    cleaned = normalize_space(str(value))
    if not cleaned:
        return None

    if cleaned.lower() in {"n/a", "na", "none", "-", "--", "tba", "unknown"}:
        return None

    return cleaned


def resolve_table_sku_key(headers):
    normalized_headers = [normalize_header(header) for header in (headers or [])]

    # Keep the existing Toy# behavior first, then fall back to Cast# only when a
    # Toy-style SKU column is not present on that table.
    for header in normalized_headers:
        condensed = header.replace("_", "")
        if condensed in {"toynumber", "toynumbernumber"}:
            return header
    for header in normalized_headers:
        if header == "toy":
            return header
    for header in normalized_headers:
        condensed = header.replace("_", "")
        if condensed == "castnumber":
            return header
    for header in normalized_headers:
        if header == "cast":
            return header

    for header in normalized_headers:
        if header.startswith("toy") and "number" in header:
            return header
    for header in normalized_headers:
        if header.startswith("cast") and "number" in header:
            return header
    return None


def extract_stage_sku(row, sku_key):
    if not sku_key:
        return None
    return _clean_stage_sku(row.get(sku_key))


def build_temp_stage_sku(row, sku_key=None, context="row"):
    raw_hints = [
        row.get(sku_key) if sku_key else None,
        row.get("toy_number"),
        row.get("toy_number_number"),
        row.get("cast_number"),
        row.get("cast"),
    ]
    raw_hint = next((normalize_space(str(value)) for value in raw_hints if normalize_space(str(value or ""))), "")
    suffix = uuid.uuid4().hex[:10]
    if raw_hint:
        return f"TEMP-{context}-{suffix}-{re.sub(r'[^A-Z0-9]+', '-', raw_hint.upper()).strip('-')}"
    return f"TEMP-{context}-{suffix}"


def build_stage_row(
    *,
    job_id,
    source_url,
    page_title,
    page_type,
    release_year,
    series_name,
    section_name,
    sku,
    title,
    notes,
    raw_html_s3_key,
    raw_row,
):
    return {
        "job_id": job_id,
        "source_url": source_url,
        "page_title": page_title,
        "page_type": page_type,
        "release_year": release_year,
        "series_name": series_name,
        "section_name": section_name,
        "sku": sku,
        "title": title,
        "notes": notes,
        "raw_html_s3_key": raw_html_s3_key,
        "raw_row": raw_row,
        "parser_version": PARSER_VERSION,
        "parse_status": "parsed",
        "review_status": "flagged" if str(sku or "").startswith("TEMP-") else "pending",
        "review_notes": "Missing reliable SKU from source page." if str(sku or "").startswith("TEMP-") else None,
    }


def parse_year_list_page(soup, source_url, page_title, raw_html_s3_key, job_id):
    release_year = extract_year_from_title(page_title)
    staged_rows = []

    for table in soup.select(".wikitable"):
        headers, rows = extract_table(table)
        normalized_headers = set(headers)
        sku_key = resolve_table_sku_key(headers)
        if not sku_key:
            continue
        if "model_name" not in normalized_headers and "casting_name" not in normalized_headers:
            continue

        for row in rows:
            sku = extract_stage_sku(row, sku_key) or build_temp_stage_sku(row, sku_key, "year")
            title = row.get("model_name") or row.get("casting_name")
            if not sku or not title:
                continue

            staged_rows.append(
                build_stage_row(
                    job_id=job_id,
                    source_url=source_url,
                    page_title=page_title,
                    page_type="year_list",
                    release_year=release_year,
                    series_name=None,
                    section_name=None,
                    sku=sku,
                    title=title,
                    notes=row.get("notes"),
                    raw_html_s3_key=raw_html_s3_key,
                    raw_row=row,
                )
            )

    return staged_rows


def parse_series_sections_page(soup, source_url, page_title, raw_html_s3_key, job_id):
    staged_rows = []

    for table in soup.select(".wikitable"):
        headers, rows = extract_table(table)
        normalized_headers = set(headers)
        sku_key = resolve_table_sku_key(headers)
        if not sku_key:
            continue
        if "casting_name" not in normalized_headers and "model_name" not in normalized_headers:
            continue

        section_name = extract_section_heading(table)
        for row in rows:
            sku = extract_stage_sku(row, sku_key) or build_temp_stage_sku(row, sku_key, "series")
            title = row.get("casting_name") or row.get("model_name")
            if not sku or not title:
                continue

            staged_rows.append(
                build_stage_row(
                    job_id=job_id,
                    source_url=source_url,
                    page_title=page_title,
                    page_type="series_sections",
                    release_year=None,
                    series_name=page_title,
                    section_name=section_name,
                    sku=sku,
                    title=title,
                    notes=row.get("notes"),
                    raw_html_s3_key=raw_html_s3_key,
                    raw_row=row,
                )
            )

    return staged_rows


def parse_casting_page(soup, source_url, page_title, raw_html_s3_key, job_id, discovered_from=None):
    grouped = {}

    for table in soup.find_all("table"):
        headers, rows = extract_table(table)
        normalized_headers = set(headers)
        sku_key = resolve_table_sku_key(headers)
        if not sku_key:
            continue

        # Casting pages usually include year/series/col number style release tables.
        if not ({"year", "series"} & normalized_headers or "col_number" in normalized_headers):
            continue

        section_name = extract_section_heading(table)

        for row in rows:
            sku = extract_stage_sku(row, sku_key) or build_temp_stage_sku(row, sku_key, "cast")

            variation = dict(row)
            if section_name:
                variation["section_name"] = section_name
            variation["resolved_sku"] = sku

            bucket = grouped.setdefault(
                sku,
                {
                    "sku": sku,
                    "release_years": set(),
                    "series_names": set(),
                    "section_names": set(),
                    "notes": [],
                    "variations": [],
                },
            )

            year_value = parse_optional_year(row.get("year"))
            if year_value:
                bucket["release_years"].add(year_value)

            series_value = normalize_space(row.get("series"))
            if series_value:
                bucket["series_names"].add(series_value)

            if section_name:
                bucket["section_names"].add(section_name)

            notes_value = normalize_space(row.get("notes"))
            if notes_value:
                bucket["notes"].append(notes_value)

            bucket["variations"].append(variation)

    staged_rows = []
    for sku, bucket in grouped.items():
        release_years = sorted(bucket["release_years"])
        series_names = sorted(bucket["series_names"])
        section_names = sorted(bucket["section_names"])
        notes = sorted(set(bucket["notes"]))

        staged_rows.append(
            build_stage_row(
                job_id=job_id,
                source_url=source_url,
                page_title=page_title,
                page_type="casting_page",
                release_year=release_years[0] if release_years else None,
                series_name=series_names[0] if len(series_names) == 1 else None,
                section_name=section_names[0] if len(section_names) == 1 else None,
                sku=sku,
                title=page_title,
                notes=" | ".join(notes) if notes else None,
                raw_html_s3_key=raw_html_s3_key,
                raw_row={
                    "casting_name": page_title,
                    "source_url": source_url,
                    "discovered_from": discovered_from,
                    "variation_count": len(bucket["variations"]),
                    "release_years": release_years,
                    "series_names": series_names,
                    "section_names": section_names,
                    "variations": bucket["variations"],
                },
            )
        )

    return staged_rows


def parse_hot_wheels_page(url, html, job_id, page_title_override=None, discovered_from=None):
    soup = BeautifulSoup(html, "html.parser")
    page_title = get_page_title(soup, page_title_override)
    raw_html_s3_key = upload_raw_html(url, html)

    if is_year_list_page(page_title):
        page_type = "year_list"
        rows = parse_year_list_page(soup, url, page_title, raw_html_s3_key, job_id)
    else:
        rows = parse_casting_page(
            soup,
            url,
            page_title,
            raw_html_s3_key,
            job_id,
            discovered_from=discovered_from,
        )
        if rows:
            page_type = "casting_page"
        else:
            page_type = "series_sections"
            rows = parse_series_sections_page(soup, url, page_title, raw_html_s3_key, job_id)

    return {
        "page_title": page_title,
        "page_type": page_type,
        "raw_html_s3_key": raw_html_s3_key,
        "rows": rows,
    }


def dedupe_stage_rows(items):
    deduped = {}

    for item in items:
        key = (item["source_url"], item["sku"], item["title"])
        existing = deduped.get(key)
        if not existing:
            deduped[key] = item
            continue

        existing_score = int(bool(existing.get("section_name"))) + int(bool(existing.get("notes")))
        candidate_score = int(bool(item.get("section_name"))) + int(bool(item.get("notes")))

        # Series pages can repeat the same SKU/title across multiple sections
        # or duplicate tables. Keep one canonical staged row per unique import
        # key and prefer the richer record when duplicates collide.
        if candidate_score > existing_score:
            deduped[key] = item

    return list(deduped.values())


def upsert_stage_rows(conn, items):
    if not items:
        return 0

    items = dedupe_stage_rows(items)

    values = [
        (
            item["source_url"],
            item.get("job_id"),
            item["page_title"],
            item["page_type"],
            item.get("release_year"),
            item.get("series_name"),
            item.get("section_name"),
            item["sku"],
            item["title"],
            item.get("notes"),
            item.get("raw_html_s3_key"),
            Json(item.get("raw_row") or {}),
            item["parser_version"],
            item["parse_status"],
            item["review_status"],
            item.get("review_notes"),
        )
        for item in items
    ]

    with conn.cursor() as cur:
        sql = """
        INSERT INTO hot_wheels_fandom_staging (
            source_url,
            job_id,
            page_title,
            page_type,
            release_year,
            series_name,
            section_name,
            sku,
            title,
            notes,
            raw_html_s3_key,
            raw_row,
            parser_version,
            parse_status,
            review_status,
            review_notes
        )
        VALUES %s
        ON CONFLICT (source_url, sku, title)
        DO UPDATE SET
            job_id = EXCLUDED.job_id,
            page_title = EXCLUDED.page_title,
            page_type = EXCLUDED.page_type,
            release_year = EXCLUDED.release_year,
            series_name = EXCLUDED.series_name,
            section_name = EXCLUDED.section_name,
            notes = EXCLUDED.notes,
            raw_html_s3_key = EXCLUDED.raw_html_s3_key,
            raw_row = EXCLUDED.raw_row,
            parser_version = EXCLUDED.parser_version,
            parse_status = EXCLUDED.parse_status,
            review_status = EXCLUDED.review_status,
            review_notes = EXCLUDED.review_notes,
            updated_at = now()
        """
        execute_values(cur, sql, values)
        conn.commit()

    return len(items)


def discover_category_member_urls(url):
    page_name = extract_fandom_page_name(url)
    if not is_category_page_name(page_name):
        return []

    member_urls = []
    continuation = None
    seen_titles = set()

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": page_name,
            "cmnamespace": 0,
            "cmlimit": "max",
            "format": "json",
            "formatversion": "2",
        }
        if continuation:
            params["cmcontinue"] = continuation

        payload = fetch_fandom_api_json(url, params)
        for member in (payload.get("query") or {}).get("categorymembers") or []:
            title = normalize_space(member.get("title"))
            if not title or title in seen_titles:
                continue
            if should_skip_category_member_title(title):
                continue
            seen_titles.add(title)
            member_urls.append(build_fandom_page_url(url, title))

        continuation = ((payload.get("continue") or {}).get("cmcontinue"))
        if not continuation:
            break

    return member_urls


def crawl_page(url, job_id, log, discovered_from=None):
    log(f"Crawling Hot Wheels catalog page {url}")
    time.sleep(REQUEST_DELAY)
    try:
        # Fandom front-door page requests are frequently blocked from Lambda
        # with 403s, while the MediaWiki parse API is much more reliable for
        # crawler traffic. Use the API first and only fall back to direct HTML
        # if the API path fails for some unexpected reason.
        html, page_title = fetch_fandom_page_html_via_api(url)
        return parse_hot_wheels_page(url, html, job_id, page_title, discovered_from=discovered_from)
    except Exception as error:
        log(f"Fandom API parse fetch failed for {url}: {error}. Falling back to direct page fetch.")
        resp = safe_get(url)
        return parse_hot_wheels_page(url, resp.text, job_id, discovered_from=discovered_from)


def handler(event, context):
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])
    else:
        body = event

    job_id = body.get("job_id") or f"hotwheels-{int(time.time())}"
    one_month = 30 * 24 * 60 * 60

    def log(message):
        timestamp = int(time.time() * 1000)
        print(f"[JOB {job_id}] {message}")
        log_table.put_item(
            Item={
                "jobId": job_id,
                "ts": timestamp,
                "message": message,
                "expireAt": int(time.time()) + one_month,
            }
        )

    log("Start Hot Wheels staging crawl")

    page_urls = body.get("page_urls") or []
    if not page_urls:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "page_urls is required"}),
        }

    try:
        creds = get_db_credentials()
        conn = get_db_conn(creds)

        total_rows = 0
        page_summaries = []

        for page_url in page_urls:
            crawl_targets = [(page_url, None)]

            if is_category_page_name(extract_fandom_page_name(page_url)):
                try:
                    member_urls = discover_category_member_urls(page_url)
                    log(f"Discovered {len(member_urls)} casting pages from {page_url}")
                    page_summaries.append(
                        {
                            "source_url": page_url,
                            "page_type": "category_members",
                            "discovered_count": len(member_urls),
                        }
                    )
                    crawl_targets = [(member_url, page_url) for member_url in member_urls]
                except Exception as exc:
                    log(f"Failed discovering category members for {page_url}: {exc}")
                    log(traceback.format_exc())
                    page_summaries.append(
                        {
                            "source_url": page_url,
                            "page_type": "category_members",
                            "error": str(exc),
                        }
                    )
                    continue

            for target_url, discovered_from in crawl_targets:
                try:
                    result = crawl_page(target_url, job_id, log, discovered_from=discovered_from)
                    inserted_count = upsert_stage_rows(conn, result["rows"])
                    total_rows += inserted_count
                    page_summaries.append(
                        {
                            "source_url": target_url,
                            "discovered_from": discovered_from,
                            "page_title": result["page_title"],
                            "page_type": result["page_type"],
                            "row_count": inserted_count,
                        }
                    )
                    log(
                        f"Parsed {inserted_count} staged rows from {target_url} "
                        f"({result['page_type']})"
                    )
                except Exception as exc:
                    log(f"Failed crawling {target_url}: {exc}")
                    log(traceback.format_exc())
                    page_summaries.append(
                        {
                            "source_url": target_url,
                            "discovered_from": discovered_from,
                            "error": str(exc),
                        }
                    )

        conn.close()
        log("DONE")

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(
                {
                    "message": "hot wheels staging crawl completed",
                    "parser_version": PARSER_VERSION,
                    "total_rows": total_rows,
                    "pages": page_summaries,
                }
            ),
        }
    except Exception as exc:
        log(f"Failed to crawl: {exc}")
        log(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)}),
        }
