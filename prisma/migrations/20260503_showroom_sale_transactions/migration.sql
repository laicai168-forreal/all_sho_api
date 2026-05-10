CREATE TABLE IF NOT EXISTS showroom_sale_transactions (
    id uuid PRIMARY KEY,
    post_id uuid NOT NULL UNIQUE REFERENCES showroom_posts(id) ON DELETE CASCADE,
    seller_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    buyer_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT showroom_sale_transactions_seller_buyer_check CHECK (seller_user_id <> buyer_user_id)
);

CREATE INDEX IF NOT EXISTS idx_showroom_sale_transactions_seller
    ON showroom_sale_transactions (seller_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_sale_transactions_buyer
    ON showroom_sale_transactions (buyer_user_id, created_at DESC);
