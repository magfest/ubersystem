-- Revert rams-core:add-badge-statuses from pg

BEGIN;

ALTER TABLE attendee
        DROP COLUMN badge_status;

COMMIT;
