-- Verify rams-core:add-badge-statuses on pg

BEGIN;

SELECT column_name FROM information_schema.columns WHERE table_name = 'attendee' AND column_name = 'badge_status';

ROLLBACK;
