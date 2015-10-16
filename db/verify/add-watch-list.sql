-- Verify rams-core:add-watch-list on pg

BEGIN;

SELECT column_name FROM information_schema.columns WHERE table_name = 'attendee' AND column_name = 'watchlist_id';

SELECT * FROM watch_list

ROLLBACK;
