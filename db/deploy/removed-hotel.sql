-- Deploy rams-core:removed-hotel to pg

BEGIN;

DROP TABLE hotel_requests;

DROP TABLE room;

DROP TABLE room_assignment;

ALTER TABLE attendee
	DROP COLUMN fire_safety_cert,
	ADD COLUMN can_work_setup boolean DEFAULT false NOT NULL,
	ADD COLUMN can_work_teardown boolean DEFAULT false NOT NULL;

COMMIT;
