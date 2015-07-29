-- Deploy rams-core:add-badge-statuses to pg

BEGIN;

ALTER TABLE attendee
        ADD COLUMN badge_status integer DEFAULT 163076611 NOT NULL;

COMMIT;
