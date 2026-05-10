CREATE TABLE IF NOT EXISTS showroom_reports (
    id uuid PRIMARY KEY,
    reporter_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id uuid REFERENCES showroom_posts(id) ON DELETE CASCADE,
    comment_id uuid REFERENCES showroom_post_comments(id) ON DELETE CASCADE,
    reason text NOT NULL,
    details text,
    status text NOT NULL DEFAULT 'open',
    created_at timestamp without time zone DEFAULT now(),
    reviewed_at timestamp without time zone,
    reviewed_by uuid REFERENCES users(id) ON DELETE SET NULL,
    review_notes text,
    CONSTRAINT showroom_reports_target_check CHECK (
        (post_id IS NOT NULL AND comment_id IS NULL)
        OR (post_id IS NULL AND comment_id IS NOT NULL)
    ),
    CONSTRAINT showroom_reports_status_check CHECK (status IN ('open', 'reviewed', 'dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_showroom_reports_status_created
    ON showroom_reports (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_reports_reporter_created
    ON showroom_reports (reporter_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_reports_post_id
    ON showroom_reports (post_id)
    WHERE post_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_showroom_reports_comment_id
    ON showroom_reports (comment_id)
    WHERE comment_id IS NOT NULL;
