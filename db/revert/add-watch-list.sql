-- Revert rams-core:add-watch-list from pg

BEGIN;

ALTER TABLE attendee
        DROP CONSTRAINT attendee_watchlist_id_key;

ALTER TABLE attendee
        DROP CONSTRAINT attendee_watchlist_id_fkey;

DROP TABLE watch_list;

COMMIT;
