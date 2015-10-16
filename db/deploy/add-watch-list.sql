-- Deploy rams-core:add-watch-list to pg

BEGIN;

CREATE TABLE watch_list (
        id uuid NOT NULL,
        first_names character varying DEFAULT ''::character varying NOT NULL,
        last_name character varying DEFAULT ''::character varying NOT NULL,
        email character varying DEFAULT ''::character varying NOT NULL,
        birthdate date,
        reason character varying DEFAULT ''::character varying NOT NULL,
        "action" character varying DEFAULT ''::character varying NOT NULL,
        active boolean DEFAULT true NOT NULL
);

ALTER TABLE attendee
        ADD COLUMN watchlist_id uuid;

ALTER TABLE watch_list
        ADD CONSTRAINT watch_list_pkey PRIMARY KEY (id);

ALTER TABLE attendee
        ADD CONSTRAINT attendee_watchlist_id_key UNIQUE (watchlist_id);

ALTER TABLE attendee
        ADD CONSTRAINT attendee_watchlist_id_fkey FOREIGN KEY (watchlist_id) REFERENCES watch_list(id) ON DELETE SET NULL;

COMMIT;
