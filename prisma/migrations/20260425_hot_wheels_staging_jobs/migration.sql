ALTER TABLE hot_wheels_fandom_staging
ADD COLUMN IF NOT EXISTS job_id text;

CREATE INDEX IF NOT EXISTS hot_wheels_fandom_staging_job_id_idx
    ON hot_wheels_fandom_staging (job_id);
