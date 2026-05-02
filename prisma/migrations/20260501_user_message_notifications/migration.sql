ALTER TABLE users
ADD COLUMN IF NOT EXISTS message_notifications_muted boolean NOT NULL DEFAULT false;
