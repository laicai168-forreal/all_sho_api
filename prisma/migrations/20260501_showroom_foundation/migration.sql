CREATE TABLE IF NOT EXISTS showroom_posts (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_type text NOT NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    visibility text NOT NULL DEFAULT 'public',
    status text NOT NULL DEFAULT 'published',
    like_count integer NOT NULL DEFAULT 0,
    comment_count integer NOT NULL DEFAULT 0,
    image_count integer NOT NULL DEFAULT 0,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    published_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT showroom_posts_type_check CHECK (post_type IN ('display_only', 'selling')),
    CONSTRAINT showroom_posts_visibility_check CHECK (visibility IN ('public')),
    CONSTRAINT showroom_posts_status_check CHECK (status IN ('published', 'hidden', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_showroom_posts_user_created
    ON showroom_posts (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_posts_type_created
    ON showroom_posts (post_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_showroom_posts_created
    ON showroom_posts (created_at DESC);

CREATE TABLE IF NOT EXISTS showroom_selling_details (
    post_id uuid PRIMARY KEY REFERENCES showroom_posts(id) ON DELETE CASCADE,
    price numeric(12, 2) NOT NULL,
    currency text NOT NULL DEFAULT 'USD',
    condition text,
    location text,
    shipping_supported boolean NOT NULL DEFAULT false,
    selling_status text NOT NULL DEFAULT 'available',
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT showroom_selling_details_status_check CHECK (selling_status IN ('available', 'reserved', 'sold'))
);

CREATE TABLE IF NOT EXISTS showroom_post_images (
    id uuid PRIMARY KEY,
    post_id uuid NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    image_url text NOT NULL,
    object_key text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_showroom_post_images_post_sort
    ON showroom_post_images (post_id, sort_order);

CREATE TABLE IF NOT EXISTS showroom_tags (
    id uuid PRIMARY KEY,
    tag_key text NOT NULL UNIQUE,
    display_name text NOT NULL,
    created_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS showroom_post_tag_links (
    post_id uuid NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES showroom_tags(id) ON DELETE CASCADE,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_showroom_post_tag_links_tag_id
    ON showroom_post_tag_links (tag_id, created_at DESC);

CREATE TABLE IF NOT EXISTS showroom_post_car_links (
    post_id uuid NOT NULL REFERENCES showroom_posts(id) ON DELETE CASCADE,
    car_id uuid NOT NULL REFERENCES cars(id) ON DELETE RESTRICT,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, car_id)
);

CREATE INDEX IF NOT EXISTS idx_showroom_post_car_links_car_id
    ON showroom_post_car_links (car_id, created_at DESC);
