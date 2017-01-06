-- Revert rams-core:removed-hotel from pg

BEGIN;

CREATE TABLE hotel_requests (
	id uuid NOT NULL,
	attendee_id uuid NOT NULL,
	nights character varying DEFAULT ''::character varying NOT NULL,
	wanted_roommates character varying DEFAULT ''::character varying NOT NULL,
	unwanted_roommates character varying DEFAULT ''::character varying NOT NULL,
	special_needs character varying DEFAULT ''::character varying NOT NULL,
	approved boolean DEFAULT false NOT NULL
);

CREATE TABLE room (
	id uuid NOT NULL,
	department integer NOT NULL,
	notes character varying DEFAULT ''::character varying NOT NULL,
	nights character varying DEFAULT ''::character varying NOT NULL,
	created timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE TABLE room_assignment (
	id uuid NOT NULL,
	room_id uuid NOT NULL,
	attendee_id uuid NOT NULL
);

ALTER TABLE attendee
	DROP COLUMN can_work_setup,
	DROP COLUMN can_work_teardown,
	ADD COLUMN fire_safety_cert character varying DEFAULT ''::character varying NOT NULL;

ALTER TABLE hotel_requests
	ADD CONSTRAINT hotel_requests_pkey PRIMARY KEY (id);

ALTER TABLE room
	ADD CONSTRAINT room_pkey PRIMARY KEY (id);

ALTER TABLE room_assignment
	ADD CONSTRAINT room_assignment_pkey PRIMARY KEY (id);

ALTER TABLE hotel_requests
	ADD CONSTRAINT hotel_requests_attendee_id_key UNIQUE (attendee_id);

ALTER TABLE hotel_requests
	ADD CONSTRAINT hotel_requests_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);

ALTER TABLE room_assignment
	ADD CONSTRAINT room_assignment_attendee_id_key UNIQUE (attendee_id);

ALTER TABLE room_assignment
	ADD CONSTRAINT room_assignment_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);

ALTER TABLE room_assignment
	ADD CONSTRAINT room_assignment_room_id_fkey FOREIGN KEY (room_id) REFERENCES room(id);

COMMIT;
