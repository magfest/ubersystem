-- Deploy rams-core:removed-tabletop to pg

BEGIN;

SET search_path = public, pg_catalog;

DROP TABLE checkout;
DROP TABLE game;

COMMIT;
