CREATE TABLE IF NOT EXISTS user_follows (
    follower_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (follower_id, followed_user_id),
    CONSTRAINT user_follows_no_self_follow CHECK (follower_id <> followed_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_follows_followed_user_id
    ON user_follows (followed_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_follows_follower_id
    ON user_follows (follower_id, created_at DESC);
