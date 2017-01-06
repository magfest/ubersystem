-- Revert rams-core:removed-tabletop from pg

BEGIN;

SET search_path = public, pg_catalog;

CREATE TABLE checkout (
	id uuid NOT NULL,
	game_id uuid NOT NULL,
	attendee_id uuid NOT NULL,
	checked_out timestamp without time zone NOT NULL,
	returned timestamp without time zone
);

CREATE TABLE game (
	id uuid NOT NULL,
	code character varying DEFAULT ''::character varying NOT NULL,
	name character varying DEFAULT ''::character varying NOT NULL,
	attendee_id uuid NOT NULL,
	returned boolean DEFAULT false NOT NULL
);

ALTER TABLE checkout
	ADD CONSTRAINT checkout_pkey PRIMARY KEY (id);

ALTER TABLE game
	ADD CONSTRAINT game_pkey PRIMARY KEY (id);

ALTER TABLE checkout
	ADD CONSTRAINT checkout_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);

ALTER TABLE checkout
	ADD CONSTRAINT checkout_game_id_fkey FOREIGN KEY (game_id) REFERENCES game(id);

ALTER TABLE game
	ADD CONSTRAINT game_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);

COMMIT;
