-- Revert rams-core:removed-panels from pg

BEGIN;

SET search_path = public, pg_catalog;

CREATE TABLE assigned_panelist (
	id uuid NOT NULL,
	attendee_id uuid NOT NULL,
	event_id uuid NOT NULL
);

CREATE TABLE event (
	id uuid NOT NULL,
	location integer NOT NULL,
	start_time timestamp without time zone NOT NULL,
	duration integer NOT NULL,
	name character varying DEFAULT ''::character varying NOT NULL,
	description character varying DEFAULT ''::character varying NOT NULL
);

ALTER TABLE assigned_panelist
	ADD CONSTRAINT assigned_panelist_pkey PRIMARY KEY (id);

ALTER TABLE event
	ADD CONSTRAINT event_pkey PRIMARY KEY (id);

ALTER TABLE assigned_panelist
	ADD CONSTRAINT assigned_panelist_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE CASCADE;

ALTER TABLE assigned_panelist
	ADD CONSTRAINT assigned_panelist_event_id_fkey FOREIGN KEY (event_id) REFERENCES event(id) ON DELETE CASCADE;

COMMIT;
