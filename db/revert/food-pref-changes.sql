-- Revert rams-core:food-pref-changes from pg

BEGIN;

ALTER TABLE food_restrictions
	ADD COLUMN no_cheese boolean DEFAULT false NOT NULL,
	ALTER COLUMN sandwich_pref TYPE integer /* TYPE change - table: food_restrictions original: character varying new: integer */,
	ALTER COLUMN sandwich_pref DROP DEFAULT;

COMMIT;
