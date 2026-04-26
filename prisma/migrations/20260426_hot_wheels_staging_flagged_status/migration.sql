ALTER TABLE hot_wheels_fandom_staging
DROP CONSTRAINT IF EXISTS hot_wheels_fandom_staging_review_status_check;

ALTER TABLE hot_wheels_fandom_staging
ADD CONSTRAINT hot_wheels_fandom_staging_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'imported', 'flagged'));
