CREATE TABLE showroom_transaction_reviews (
    id UUID PRIMARY KEY,
    showroom_post_id UUID NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    seller_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    buyer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reviewer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reviewee_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT showroom_transaction_reviews_unique UNIQUE (showroom_post_id, reviewer_user_id, reviewee_user_id),
    CONSTRAINT showroom_transaction_reviews_not_self CHECK (reviewer_user_id <> reviewee_user_id)
);

CREATE INDEX idx_showroom_transaction_reviews_reviewee ON showroom_transaction_reviews(reviewee_user_id, created_at DESC);
CREATE INDEX idx_showroom_transaction_reviews_transaction ON showroom_transaction_reviews(showroom_post_id, seller_user_id, buyer_user_id);
