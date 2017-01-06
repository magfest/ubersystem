-- Deploy rams-core:food-pref-changes to pg

BEGIN;

ALTER TABLE food_restrictions
	DROP COLUMN no_cheese,
	ALTER COLUMN sandwich_pref TYPE character varying /* TYPE change - table: food_restrictions original: integer new: character varying */,
	ALTER COLUMN sandwich_pref SET DEFAULT ''::character varying;

COMMIT;
