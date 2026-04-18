ALTER TABLE users
ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'customer';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_role_check'
    ) THEN
        ALTER TABLE users
        ADD CONSTRAINT users_role_check
        CHECK (role IN ('customer', 'admin'));
    END IF;
END $$;

ALTER TABLE cars
ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES users(id),
ADD COLUMN IF NOT EXISTS updated_by uuid REFERENCES users(id),
ADD COLUMN IF NOT EXISTS updated_at timestamp without time zone DEFAULT NOW();

CREATE TABLE IF NOT EXISTS car_change_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    car_id uuid REFERENCES cars(id) ON DELETE SET NULL,
    submitted_by uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending',
    request_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    uploaded_images jsonb NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by uuid REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at timestamp without time zone,
    review_notes text,
    created_at timestamp without time zone NOT NULL DEFAULT NOW(),
    updated_at timestamp without time zone NOT NULL DEFAULT NOW(),
    CONSTRAINT car_change_requests_status_check CHECK (
        status IN ('pending', 'approved', 'rejected')
    )
);

CREATE INDEX IF NOT EXISTS idx_car_change_requests_submitted_by
ON car_change_requests (submitted_by, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_car_change_requests_status
ON car_change_requests (status, created_at DESC);
