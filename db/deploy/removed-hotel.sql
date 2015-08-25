-- Deploy rams-core:removed-hotel to pg

BEGIN;

CREATE SCHEMA sqitch;

COMMENT ON SCHEMA sqitch IS 'Sqitch database deployment metadata v1.0.';

SET search_path = public, pg_catalog;

DROP TABLE hotel_requests;

DROP TABLE room;

DROP TABLE room_assignment;

ALTER TABLE attendee
	DROP COLUMN fire_safety_cert,
	ADD COLUMN can_work_setup boolean DEFAULT false NOT NULL,
	ADD COLUMN can_work_teardown boolean DEFAULT false NOT NULL;

SET search_path = sqitch, pg_catalog;

CREATE TABLE changes (
	change_id text NOT NULL,
	script_hash text,
	change text NOT NULL,
	project text NOT NULL,
	note text DEFAULT ''::text NOT NULL,
	committed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
	committer_name text NOT NULL,
	committer_email text NOT NULL,
	planned_at timestamp with time zone NOT NULL,
	planner_name text NOT NULL,
	planner_email text NOT NULL
);

COMMENT ON TABLE changes IS 'Tracks the changes currently deployed to the database.';

COMMENT ON COLUMN changes.change_id IS 'Change primary key.';

COMMENT ON COLUMN changes.script_hash IS 'Deploy script SHA-1 hash.';

COMMENT ON COLUMN changes.change IS 'Name of a deployed change.';

COMMENT ON COLUMN changes.project IS 'Name of the Sqitch project to which the change belongs.';

COMMENT ON COLUMN changes.note IS 'Description of the change.';

COMMENT ON COLUMN changes.committed_at IS 'Date the change was deployed.';

COMMENT ON COLUMN changes.committer_name IS 'Name of the user who deployed the change.';

COMMENT ON COLUMN changes.committer_email IS 'Email address of the user who deployed the change.';

COMMENT ON COLUMN changes.planned_at IS 'Date the change was added to the plan.';

COMMENT ON COLUMN changes.planner_name IS 'Name of the user who planed the change.';

COMMENT ON COLUMN changes.planner_email IS 'Email address of the user who planned the change.';

CREATE TABLE dependencies (
	change_id text NOT NULL,
	type text NOT NULL,
	dependency text NOT NULL,
	dependency_id text
);

COMMENT ON TABLE dependencies IS 'Tracks the currently satisfied dependencies.';

COMMENT ON COLUMN dependencies.change_id IS 'ID of the depending change.';

COMMENT ON COLUMN dependencies.type IS 'Type of dependency.';

COMMENT ON COLUMN dependencies.dependency IS 'Dependency name.';

COMMENT ON COLUMN dependencies.dependency_id IS 'Change ID the dependency resolves to.';

CREATE TABLE events (
	event text NOT NULL,
	change_id text NOT NULL,
	change text NOT NULL,
	project text NOT NULL,
	note text DEFAULT ''::text NOT NULL,
	requires text[] DEFAULT '{}'::text[] NOT NULL,
	conflicts text[] DEFAULT '{}'::text[] NOT NULL,
	tags text[] DEFAULT '{}'::text[] NOT NULL,
	committed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
	committer_name text NOT NULL,
	committer_email text NOT NULL,
	planned_at timestamp with time zone NOT NULL,
	planner_name text NOT NULL,
	planner_email text NOT NULL
);

COMMENT ON TABLE events IS 'Contains full history of all deployment events.';

COMMENT ON COLUMN events.event IS 'Type of event.';

COMMENT ON COLUMN events.change_id IS 'Change ID.';

COMMENT ON COLUMN events.change IS 'Change name.';

COMMENT ON COLUMN events.project IS 'Name of the Sqitch project to which the change belongs.';

COMMENT ON COLUMN events.note IS 'Description of the change.';

COMMENT ON COLUMN events.requires IS 'Array of the names of required changes.';

COMMENT ON COLUMN events.conflicts IS 'Array of the names of conflicting changes.';

COMMENT ON COLUMN events.tags IS 'Tags associated with the change.';

COMMENT ON COLUMN events.committed_at IS 'Date the event was committed.';

COMMENT ON COLUMN events.committer_name IS 'Name of the user who committed the event.';

COMMENT ON COLUMN events.committer_email IS 'Email address of the user who committed the event.';

COMMENT ON COLUMN events.planned_at IS 'Date the event was added to the plan.';

COMMENT ON COLUMN events.planner_name IS 'Name of the user who planed the change.';

COMMENT ON COLUMN events.planner_email IS 'Email address of the user who plan planned the change.';

CREATE TABLE projects (
	project text NOT NULL,
	uri text,
	created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
	creator_name text NOT NULL,
	creator_email text NOT NULL
);

COMMENT ON TABLE projects IS 'Sqitch projects deployed to this database.';

COMMENT ON COLUMN projects.project IS 'Unique Name of a project.';

COMMENT ON COLUMN projects.uri IS 'Optional project URI';

COMMENT ON COLUMN projects.created_at IS 'Date the project was added to the database.';

COMMENT ON COLUMN projects.creator_name IS 'Name of the user who added the project.';

COMMENT ON COLUMN projects.creator_email IS 'Email address of the user who added the project.';

CREATE TABLE releases (
	version real NOT NULL,
	installed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
	installer_name text NOT NULL,
	installer_email text NOT NULL
);

COMMENT ON TABLE releases IS 'Sqitch registry releases.';

COMMENT ON COLUMN releases.version IS 'Version of the Sqitch registry.';

COMMENT ON COLUMN releases.installed_at IS 'Date the registry release was installed.';

COMMENT ON COLUMN releases.installer_name IS 'Name of the user who installed the registry release.';

COMMENT ON COLUMN releases.installer_email IS 'Email address of the user who installed the registry release.';

CREATE TABLE tags (
	tag_id text NOT NULL,
	tag text NOT NULL,
	project text NOT NULL,
	change_id text NOT NULL,
	note text DEFAULT ''::text NOT NULL,
	committed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
	committer_name text NOT NULL,
	committer_email text NOT NULL,
	planned_at timestamp with time zone NOT NULL,
	planner_name text NOT NULL,
	planner_email text NOT NULL
);

COMMENT ON TABLE tags IS 'Tracks the tags currently applied to the database.';

COMMENT ON COLUMN tags.tag_id IS 'Tag primary key.';

COMMENT ON COLUMN tags.tag IS 'Project-unique tag name.';

COMMENT ON COLUMN tags.project IS 'Name of the Sqitch project to which the tag belongs.';

COMMENT ON COLUMN tags.change_id IS 'ID of last change deployed before the tag was applied.';

COMMENT ON COLUMN tags.note IS 'Description of the tag.';

COMMENT ON COLUMN tags.committed_at IS 'Date the tag was applied to the database.';

COMMENT ON COLUMN tags.committer_name IS 'Name of the user who applied the tag.';

COMMENT ON COLUMN tags.committer_email IS 'Email address of the user who applied the tag.';

COMMENT ON COLUMN tags.planned_at IS 'Date the tag was added to the plan.';

COMMENT ON COLUMN tags.planner_name IS 'Name of the user who planed the tag.';

COMMENT ON COLUMN tags.planner_email IS 'Email address of the user who planned the tag.';

ALTER TABLE changes
	ADD CONSTRAINT changes_pkey PRIMARY KEY (change_id);

ALTER TABLE dependencies
	ADD CONSTRAINT dependencies_pkey PRIMARY KEY (change_id, dependency);

ALTER TABLE events
	ADD CONSTRAINT events_pkey PRIMARY KEY (change_id, committed_at);

ALTER TABLE projects
	ADD CONSTRAINT projects_pkey PRIMARY KEY (project);

ALTER TABLE releases
	ADD CONSTRAINT releases_pkey PRIMARY KEY (version);

ALTER TABLE tags
	ADD CONSTRAINT tags_pkey PRIMARY KEY (tag_id);

ALTER TABLE changes
	ADD CONSTRAINT changes_project_script_hash_key UNIQUE (project, script_hash);

ALTER TABLE changes
	ADD CONSTRAINT changes_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;

ALTER TABLE dependencies
	ADD CONSTRAINT dependencies_check CHECK ((((type = 'require'::text) AND (dependency_id IS NOT NULL)) OR ((type = 'conflict'::text) AND (dependency_id IS NULL))));

ALTER TABLE dependencies
	ADD CONSTRAINT dependencies_change_id_fkey FOREIGN KEY (change_id) REFERENCES changes(change_id) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE dependencies
	ADD CONSTRAINT dependencies_dependency_id_fkey FOREIGN KEY (dependency_id) REFERENCES changes(change_id) ON UPDATE CASCADE;

ALTER TABLE events
	ADD CONSTRAINT events_event_check CHECK ((event = ANY (ARRAY['deploy'::text, 'revert'::text, 'fail'::text, 'merge'::text])));

ALTER TABLE events
	ADD CONSTRAINT events_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;

ALTER TABLE projects
	ADD CONSTRAINT projects_uri_key UNIQUE (uri);

ALTER TABLE tags
	ADD CONSTRAINT tags_project_tag_key UNIQUE (project, tag);

ALTER TABLE tags
	ADD CONSTRAINT tags_change_id_fkey FOREIGN KEY (change_id) REFERENCES changes(change_id) ON UPDATE CASCADE;

ALTER TABLE tags
	ADD CONSTRAINT tags_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;

COMMIT;
