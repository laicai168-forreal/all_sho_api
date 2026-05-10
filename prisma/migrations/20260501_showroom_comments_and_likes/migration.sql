CREATE TABLE IF NOT EXISTS showroom_post_comments (
    id uuid PRIMARY KEY,
    post_id uuid NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content text NOT NULL,
    status text NOT NULL DEFAULT 'published',
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT showroom_post_comments_status_check CHECK (status IN ('published', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_showroom_post_comments_post_created
    ON showroom_post_comments (post_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_post_comments_user_created
    ON showroom_post_comments (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS showroom_post_likes (
    post_id uuid NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_showroom_post_likes_user_created
    ON showroom_post_likes (user_id, created_at DESC);
