CREATE TABLE IF NOT EXISTS user_blocks (
    blocker_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (blocker_id, blocked_user_id),
    CONSTRAINT user_blocks_no_self_block CHECK (blocker_id <> blocked_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocker_id
    ON user_blocks (blocker_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked_user_id
    ON user_blocks (blocked_user_id, created_at DESC);
