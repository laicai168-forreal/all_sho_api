CREATE TABLE IF NOT EXISTS hot_wheels_fandom_staging (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url text NOT NULL,
    page_title text NOT NULL,
    page_type text NOT NULL,
    release_year integer,
    series_name text,
    section_name text,
    sku text NOT NULL,
    title text NOT NULL,
    notes text,
    raw_html_s3_key text,
    raw_row jsonb NOT NULL DEFAULT '{}'::jsonb,
    parser_version text NOT NULL,
    parse_status text NOT NULL DEFAULT 'parsed',
    review_status text NOT NULL DEFAULT 'pending',
    review_notes text,
    imported_car_id uuid REFERENCES cars(id) ON DELETE SET NULL,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT hot_wheels_fandom_staging_review_status_check
        CHECK (review_status IN ('pending', 'approved', 'rejected', 'imported')),
    CONSTRAINT hot_wheels_fandom_staging_parse_status_check
        CHECK (parse_status IN ('parsed', 'skipped', 'error'))
);

CREATE UNIQUE INDEX IF NOT EXISTS hot_wheels_fandom_staging_source_sku_title_idx
    ON hot_wheels_fandom_staging (source_url, sku, title);

CREATE INDEX IF NOT EXISTS hot_wheels_fandom_staging_review_status_idx
    ON hot_wheels_fandom_staging (review_status);

CREATE INDEX IF NOT EXISTS hot_wheels_fandom_staging_sku_idx
    ON hot_wheels_fandom_staging (sku);

CREATE INDEX IF NOT EXISTS hot_wheels_fandom_staging_source_url_idx
    ON hot_wheels_fandom_staging (source_url);
