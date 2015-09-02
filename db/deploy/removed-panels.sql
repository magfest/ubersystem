-- Deploy rams-core:removed-panels to pg

BEGIN;

SET search_path = public, pg_catalog;
DROP TABLE assigned_panelist;
DROP TABLE event;

COMMIT;
