--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: sqitch; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA sqitch;


ALTER SCHEMA sqitch OWNER TO postgres;

--
-- Name: SCHEMA sqitch; Type: COMMENT; Schema: -; Owner: postgres
--

COMMENT ON SCHEMA sqitch IS 'Sqitch database deployment metadata v1.0.';


--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: admin_account; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE admin_account (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    hashed character varying DEFAULT ''::character varying NOT NULL,
    access character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.admin_account OWNER TO m13;

--
-- Name: approved_email; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE approved_email (
    id uuid NOT NULL,
    subject character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.approved_email OWNER TO m13;

--
-- Name: arbitrary_charge; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE arbitrary_charge (
    id uuid NOT NULL,
    amount integer NOT NULL,
    what character varying DEFAULT ''::character varying NOT NULL,
    "when" timestamp without time zone NOT NULL,
    reg_station integer
);


ALTER TABLE public.arbitrary_charge OWNER TO m13;

--
-- Name: attendee; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE attendee (
    id uuid NOT NULL,
    group_id uuid,
    placeholder boolean DEFAULT false NOT NULL,
    first_name character varying DEFAULT ''::character varying NOT NULL,
    last_name character varying DEFAULT ''::character varying NOT NULL,
    email character varying DEFAULT ''::character varying NOT NULL,
    birthdate date,
    age_group integer DEFAULT 178244408,
    international boolean DEFAULT false NOT NULL,
    zip_code character varying DEFAULT ''::character varying NOT NULL,
    address1 character varying DEFAULT ''::character varying NOT NULL,
    address2 character varying DEFAULT ''::character varying NOT NULL,
    city character varying DEFAULT ''::character varying NOT NULL,
    region character varying DEFAULT ''::character varying NOT NULL,
    country character varying DEFAULT ''::character varying NOT NULL,
    no_cellphone boolean DEFAULT false NOT NULL,
    ec_phone character varying DEFAULT ''::character varying NOT NULL,
    cellphone character varying DEFAULT ''::character varying NOT NULL,
    interests character varying DEFAULT ''::character varying NOT NULL,
    found_how character varying DEFAULT ''::character varying NOT NULL,
    comments character varying DEFAULT ''::character varying NOT NULL,
    for_review character varying DEFAULT ''::character varying NOT NULL,
    admin_notes character varying DEFAULT ''::character varying NOT NULL,
    badge_num integer DEFAULT 0,
    badge_type integer DEFAULT 51352218 NOT NULL,
    badge_status integer DEFAULT 163076611 NOT NULL,
    ribbon integer DEFAULT 154973361 NOT NULL,
    affiliate character varying DEFAULT ''::character varying NOT NULL,
    shirt integer DEFAULT 0 NOT NULL,
    can_spam boolean DEFAULT false NOT NULL,
    regdesk_info character varying DEFAULT ''::character varying NOT NULL,
    extra_merch character varying DEFAULT ''::character varying NOT NULL,
    got_merch boolean DEFAULT false NOT NULL,
    reg_station integer,
    registered timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    checked_in timestamp without time zone,
    paid integer DEFAULT 121378471 NOT NULL,
    overridden_price integer,
    amount_paid integer DEFAULT 0 NOT NULL,
    amount_extra integer DEFAULT 0 NOT NULL,
    amount_refunded integer DEFAULT 0 NOT NULL,
    payment_method integer,
    badge_printed_name character varying DEFAULT ''::character varying NOT NULL,
    staffing boolean DEFAULT false NOT NULL,
    requested_depts character varying DEFAULT ''::character varying NOT NULL,
    assigned_depts character varying DEFAULT ''::character varying NOT NULL,
    trusted boolean DEFAULT false NOT NULL,
    nonshift_hours integer DEFAULT 0 NOT NULL,
    past_years character varying DEFAULT ''::character varying NOT NULL,
    can_work_setup boolean DEFAULT false NOT NULL,
    can_work_teardown boolean DEFAULT false NOT NULL
);


ALTER TABLE public.attendee OWNER TO m13;

--
-- Name: checkout; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE checkout (
    id uuid NOT NULL,
    game_id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    checked_out timestamp without time zone NOT NULL,
    returned timestamp without time zone
);


ALTER TABLE public.checkout OWNER TO m13;

--
-- Name: dept_checklist_item; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE dept_checklist_item (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    slug character varying DEFAULT ''::character varying NOT NULL,
    comments character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.dept_checklist_item OWNER TO m13;

--
-- Name: email; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE email (
    id uuid NOT NULL,
    fk_id uuid,
    model character varying DEFAULT ''::character varying NOT NULL,
    "when" timestamp without time zone NOT NULL,
    subject character varying DEFAULT ''::character varying NOT NULL,
    dest character varying DEFAULT ''::character varying NOT NULL,
    body character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.email OWNER TO m13;

--
-- Name: food_restrictions; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE food_restrictions (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    standard character varying DEFAULT ''::character varying NOT NULL,
    sandwich_pref character varying DEFAULT ''::character varying NOT NULL,
    freeform character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.food_restrictions OWNER TO m13;

--
-- Name: game; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE game (
    id uuid NOT NULL,
    code character varying DEFAULT ''::character varying NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    attendee_id uuid NOT NULL,
    returned boolean DEFAULT false NOT NULL
);


ALTER TABLE public.game OWNER TO m13;

--
-- Name: group; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE "group" (
    id uuid NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    tables double precision DEFAULT 0::double precision NOT NULL,
    address character varying DEFAULT ''::character varying NOT NULL,
    website character varying DEFAULT ''::character varying NOT NULL,
    wares character varying DEFAULT ''::character varying NOT NULL,
    description character varying DEFAULT ''::character varying NOT NULL,
    special_needs character varying DEFAULT ''::character varying NOT NULL,
    amount_paid integer DEFAULT 0 NOT NULL,
    cost integer DEFAULT 0 NOT NULL,
    auto_recalc boolean DEFAULT true NOT NULL,
    can_add boolean DEFAULT false NOT NULL,
    admin_notes character varying DEFAULT ''::character varying NOT NULL,
    status integer DEFAULT 172070601 NOT NULL,
    registered timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    approved timestamp without time zone,
    leader_id uuid
);


ALTER TABLE public."group" OWNER TO m13;

--
-- Name: job; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE job (
    id uuid NOT NULL,
    type integer DEFAULT 252034462 NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    description character varying DEFAULT ''::character varying NOT NULL,
    location integer NOT NULL,
    start_time timestamp without time zone NOT NULL,
    duration integer NOT NULL,
    weight double precision DEFAULT 1::double precision NOT NULL,
    slots integer NOT NULL,
    restricted boolean DEFAULT false NOT NULL,
    extra15 boolean DEFAULT false NOT NULL
);


ALTER TABLE public.job OWNER TO m13;

--
-- Name: m_points_for_cash; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE m_points_for_cash (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    amount integer NOT NULL,
    "when" timestamp without time zone NOT NULL
);


ALTER TABLE public.m_points_for_cash OWNER TO m13;

--
-- Name: merch_pickup; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE merch_pickup (
    id uuid NOT NULL,
    picked_up_by_id uuid NOT NULL,
    picked_up_for_id uuid NOT NULL
);


ALTER TABLE public.merch_pickup OWNER TO m13;

--
-- Name: no_shirt; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE no_shirt (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL
);


ALTER TABLE public.no_shirt OWNER TO m13;

--
-- Name: old_m_point_exchange; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE old_m_point_exchange (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    amount integer NOT NULL,
    "when" timestamp without time zone NOT NULL
);


ALTER TABLE public.old_m_point_exchange OWNER TO m13;

--
-- Name: password_reset; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE password_reset (
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    generated timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    hashed character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.password_reset OWNER TO m13;

--
-- Name: sale; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE sale (
    id uuid NOT NULL,
    attendee_id uuid,
    what character varying DEFAULT ''::character varying NOT NULL,
    cash integer DEFAULT 0 NOT NULL,
    mpoints integer DEFAULT 0 NOT NULL,
    "when" timestamp without time zone NOT NULL,
    reg_station integer,
    payment_method integer DEFAULT 251700478 NOT NULL
);


ALTER TABLE public.sale OWNER TO m13;

--
-- Name: shift; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE shift (
    id uuid NOT NULL,
    job_id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    worked integer DEFAULT 176686787 NOT NULL,
    rating integer DEFAULT 54944008 NOT NULL,
    comment character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.shift OWNER TO m13;

--
-- Name: tracking; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE tracking (
    id uuid NOT NULL,
    fk_id uuid NOT NULL,
    model character varying DEFAULT ''::character varying NOT NULL,
    "when" timestamp without time zone NOT NULL,
    who character varying DEFAULT ''::character varying NOT NULL,
    which character varying DEFAULT ''::character varying NOT NULL,
    links character varying DEFAULT ''::character varying NOT NULL,
    action integer NOT NULL,
    data character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.tracking OWNER TO m13;

SET search_path = sqitch, pg_catalog;

--
-- Name: changes; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

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


ALTER TABLE sqitch.changes OWNER TO postgres;

--
-- Name: TABLE changes; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE changes IS 'Tracks the changes currently deployed to the database.';


--
-- Name: COLUMN changes.change_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.change_id IS 'Change primary key.';


--
-- Name: COLUMN changes.script_hash; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.script_hash IS 'Deploy script SHA-1 hash.';


--
-- Name: COLUMN changes.change; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.change IS 'Name of a deployed change.';


--
-- Name: COLUMN changes.project; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.project IS 'Name of the Sqitch project to which the change belongs.';


--
-- Name: COLUMN changes.note; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.note IS 'Description of the change.';


--
-- Name: COLUMN changes.committed_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.committed_at IS 'Date the change was deployed.';


--
-- Name: COLUMN changes.committer_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.committer_name IS 'Name of the user who deployed the change.';


--
-- Name: COLUMN changes.committer_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.committer_email IS 'Email address of the user who deployed the change.';


--
-- Name: COLUMN changes.planned_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.planned_at IS 'Date the change was added to the plan.';


--
-- Name: COLUMN changes.planner_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.planner_name IS 'Name of the user who planed the change.';


--
-- Name: COLUMN changes.planner_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN changes.planner_email IS 'Email address of the user who planned the change.';


--
-- Name: dependencies; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

CREATE TABLE dependencies (
    change_id text NOT NULL,
    type text NOT NULL,
    dependency text NOT NULL,
    dependency_id text,
    CONSTRAINT dependencies_check CHECK ((((type = 'require'::text) AND (dependency_id IS NOT NULL)) OR ((type = 'conflict'::text) AND (dependency_id IS NULL))))
);


ALTER TABLE sqitch.dependencies OWNER TO postgres;

--
-- Name: TABLE dependencies; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE dependencies IS 'Tracks the currently satisfied dependencies.';


--
-- Name: COLUMN dependencies.change_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN dependencies.change_id IS 'ID of the depending change.';


--
-- Name: COLUMN dependencies.type; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN dependencies.type IS 'Type of dependency.';


--
-- Name: COLUMN dependencies.dependency; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN dependencies.dependency IS 'Dependency name.';


--
-- Name: COLUMN dependencies.dependency_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN dependencies.dependency_id IS 'Change ID the dependency resolves to.';


--
-- Name: events; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

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
    planner_email text NOT NULL,
    CONSTRAINT events_event_check CHECK ((event = ANY (ARRAY['deploy'::text, 'revert'::text, 'fail'::text, 'merge'::text])))
);


ALTER TABLE sqitch.events OWNER TO postgres;

--
-- Name: TABLE events; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE events IS 'Contains full history of all deployment events.';


--
-- Name: COLUMN events.event; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.event IS 'Type of event.';


--
-- Name: COLUMN events.change_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.change_id IS 'Change ID.';


--
-- Name: COLUMN events.change; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.change IS 'Change name.';


--
-- Name: COLUMN events.project; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.project IS 'Name of the Sqitch project to which the change belongs.';


--
-- Name: COLUMN events.note; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.note IS 'Description of the change.';


--
-- Name: COLUMN events.requires; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.requires IS 'Array of the names of required changes.';


--
-- Name: COLUMN events.conflicts; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.conflicts IS 'Array of the names of conflicting changes.';


--
-- Name: COLUMN events.tags; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.tags IS 'Tags associated with the change.';


--
-- Name: COLUMN events.committed_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.committed_at IS 'Date the event was committed.';


--
-- Name: COLUMN events.committer_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.committer_name IS 'Name of the user who committed the event.';


--
-- Name: COLUMN events.committer_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.committer_email IS 'Email address of the user who committed the event.';


--
-- Name: COLUMN events.planned_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.planned_at IS 'Date the event was added to the plan.';


--
-- Name: COLUMN events.planner_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.planner_name IS 'Name of the user who planed the change.';


--
-- Name: COLUMN events.planner_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN events.planner_email IS 'Email address of the user who plan planned the change.';


--
-- Name: projects; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

CREATE TABLE projects (
    project text NOT NULL,
    uri text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    creator_name text NOT NULL,
    creator_email text NOT NULL
);


ALTER TABLE sqitch.projects OWNER TO postgres;

--
-- Name: TABLE projects; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE projects IS 'Sqitch projects deployed to this database.';


--
-- Name: COLUMN projects.project; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN projects.project IS 'Unique Name of a project.';


--
-- Name: COLUMN projects.uri; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN projects.uri IS 'Optional project URI';


--
-- Name: COLUMN projects.created_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN projects.created_at IS 'Date the project was added to the database.';


--
-- Name: COLUMN projects.creator_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN projects.creator_name IS 'Name of the user who added the project.';


--
-- Name: COLUMN projects.creator_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN projects.creator_email IS 'Email address of the user who added the project.';


--
-- Name: releases; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

CREATE TABLE releases (
    version real NOT NULL,
    installed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    installer_name text NOT NULL,
    installer_email text NOT NULL
);


ALTER TABLE sqitch.releases OWNER TO postgres;

--
-- Name: TABLE releases; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE releases IS 'Sqitch registry releases.';


--
-- Name: COLUMN releases.version; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN releases.version IS 'Version of the Sqitch registry.';


--
-- Name: COLUMN releases.installed_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN releases.installed_at IS 'Date the registry release was installed.';


--
-- Name: COLUMN releases.installer_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN releases.installer_name IS 'Name of the user who installed the registry release.';


--
-- Name: COLUMN releases.installer_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN releases.installer_email IS 'Email address of the user who installed the registry release.';


--
-- Name: tags; Type: TABLE; Schema: sqitch; Owner: postgres; Tablespace: 
--

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


ALTER TABLE sqitch.tags OWNER TO postgres;

--
-- Name: TABLE tags; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON TABLE tags IS 'Tracks the tags currently applied to the database.';


--
-- Name: COLUMN tags.tag_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.tag_id IS 'Tag primary key.';


--
-- Name: COLUMN tags.tag; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.tag IS 'Project-unique tag name.';


--
-- Name: COLUMN tags.project; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.project IS 'Name of the Sqitch project to which the tag belongs.';


--
-- Name: COLUMN tags.change_id; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.change_id IS 'ID of last change deployed before the tag was applied.';


--
-- Name: COLUMN tags.note; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.note IS 'Description of the tag.';


--
-- Name: COLUMN tags.committed_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.committed_at IS 'Date the tag was applied to the database.';


--
-- Name: COLUMN tags.committer_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.committer_name IS 'Name of the user who applied the tag.';


--
-- Name: COLUMN tags.committer_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.committer_email IS 'Email address of the user who applied the tag.';


--
-- Name: COLUMN tags.planned_at; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.planned_at IS 'Date the tag was added to the plan.';


--
-- Name: COLUMN tags.planner_name; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.planner_name IS 'Name of the user who planed the tag.';


--
-- Name: COLUMN tags.planner_email; Type: COMMENT; Schema: sqitch; Owner: postgres
--

COMMENT ON COLUMN tags.planner_email IS 'Email address of the user who planned the tag.';


SET search_path = public, pg_catalog;

--
-- Name: _dept_checklist_item_uniq; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT _dept_checklist_item_uniq UNIQUE (attendee_id, slug);


--
-- Name: admin_account_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_attendee_id_key UNIQUE (attendee_id);


--
-- Name: admin_account_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_pkey PRIMARY KEY (id);


--
-- Name: approved_email_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY approved_email
    ADD CONSTRAINT approved_email_pkey PRIMARY KEY (id);


--
-- Name: arbitrary_charge_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY arbitrary_charge
    ADD CONSTRAINT arbitrary_charge_pkey PRIMARY KEY (id);


--
-- Name: attendee_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_pkey PRIMARY KEY (id);


--
-- Name: checkout_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY checkout
    ADD CONSTRAINT checkout_pkey PRIMARY KEY (id);


--
-- Name: dept_checklist_item_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT dept_checklist_item_pkey PRIMARY KEY (id);


--
-- Name: email_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY email
    ADD CONSTRAINT email_pkey PRIMARY KEY (id);


--
-- Name: food_restrictions_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_attendee_id_key UNIQUE (attendee_id);


--
-- Name: food_restrictions_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_pkey PRIMARY KEY (id);


--
-- Name: game_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY game
    ADD CONSTRAINT game_pkey PRIMARY KEY (id);


--
-- Name: group_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY "group"
    ADD CONSTRAINT group_pkey PRIMARY KEY (id);


--
-- Name: job_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY job
    ADD CONSTRAINT job_pkey PRIMARY KEY (id);


--
-- Name: m_points_for_cash_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY m_points_for_cash
    ADD CONSTRAINT m_points_for_cash_pkey PRIMARY KEY (id);


--
-- Name: merch_pickup_picked_up_for_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_for_id_key UNIQUE (picked_up_for_id);


--
-- Name: merch_pickup_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_pkey PRIMARY KEY (id);


--
-- Name: no_shirt_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_attendee_id_key UNIQUE (attendee_id);


--
-- Name: no_shirt_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_pkey PRIMARY KEY (id);


--
-- Name: old_m_point_exchange_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY old_m_point_exchange
    ADD CONSTRAINT old_m_point_exchange_pkey PRIMARY KEY (id);


--
-- Name: password_reset_account_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_account_id_key UNIQUE (account_id);


--
-- Name: password_reset_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_pkey PRIMARY KEY (id);


--
-- Name: sale_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY sale
    ADD CONSTRAINT sale_pkey PRIMARY KEY (id);


--
-- Name: shift_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_pkey PRIMARY KEY (id);


--
-- Name: tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY tracking
    ADD CONSTRAINT tracking_pkey PRIMARY KEY (id);


SET search_path = sqitch, pg_catalog;

--
-- Name: changes_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY changes
    ADD CONSTRAINT changes_pkey PRIMARY KEY (change_id);


--
-- Name: changes_project_script_hash_key; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY changes
    ADD CONSTRAINT changes_project_script_hash_key UNIQUE (project, script_hash);


--
-- Name: dependencies_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY dependencies
    ADD CONSTRAINT dependencies_pkey PRIMARY KEY (change_id, dependency);


--
-- Name: events_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY events
    ADD CONSTRAINT events_pkey PRIMARY KEY (change_id, committed_at);


--
-- Name: projects_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (project);


--
-- Name: projects_uri_key; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY projects
    ADD CONSTRAINT projects_uri_key UNIQUE (uri);


--
-- Name: releases_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY releases
    ADD CONSTRAINT releases_pkey PRIMARY KEY (version);


--
-- Name: tags_pkey; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (tag_id);


--
-- Name: tags_project_tag_key; Type: CONSTRAINT; Schema: sqitch; Owner: postgres; Tablespace: 
--

ALTER TABLE ONLY tags
    ADD CONSTRAINT tags_project_tag_key UNIQUE (project, tag);


SET search_path = public, pg_catalog;

--
-- Name: admin_account_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: attendee_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_group_id_fkey FOREIGN KEY (group_id) REFERENCES "group"(id) ON DELETE SET NULL;


--
-- Name: checkout_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY checkout
    ADD CONSTRAINT checkout_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: checkout_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY checkout
    ADD CONSTRAINT checkout_game_id_fkey FOREIGN KEY (game_id) REFERENCES game(id);


--
-- Name: dept_checklist_item_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT dept_checklist_item_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: fk_leader; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY "group"
    ADD CONSTRAINT fk_leader FOREIGN KEY (leader_id) REFERENCES attendee(id);


--
-- Name: food_restrictions_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: game_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY game
    ADD CONSTRAINT game_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: m_points_for_cash_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY m_points_for_cash
    ADD CONSTRAINT m_points_for_cash_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: merch_pickup_picked_up_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_by_id_fkey FOREIGN KEY (picked_up_by_id) REFERENCES attendee(id);


--
-- Name: merch_pickup_picked_up_for_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_for_id_fkey FOREIGN KEY (picked_up_for_id) REFERENCES attendee(id);


--
-- Name: no_shirt_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: old_m_point_exchange_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY old_m_point_exchange
    ADD CONSTRAINT old_m_point_exchange_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: password_reset_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_account_id_fkey FOREIGN KEY (account_id) REFERENCES admin_account(id);


--
-- Name: sale_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY sale
    ADD CONSTRAINT sale_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE SET NULL;


--
-- Name: shift_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE CASCADE;


--
-- Name: shift_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_job_id_fkey FOREIGN KEY (job_id) REFERENCES job(id) ON DELETE CASCADE;


SET search_path = sqitch, pg_catalog;

--
-- Name: changes_project_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY changes
    ADD CONSTRAINT changes_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;


--
-- Name: dependencies_change_id_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY dependencies
    ADD CONSTRAINT dependencies_change_id_fkey FOREIGN KEY (change_id) REFERENCES changes(change_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: dependencies_dependency_id_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY dependencies
    ADD CONSTRAINT dependencies_dependency_id_fkey FOREIGN KEY (dependency_id) REFERENCES changes(change_id) ON UPDATE CASCADE;


--
-- Name: events_project_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY events
    ADD CONSTRAINT events_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;


--
-- Name: tags_change_id_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY tags
    ADD CONSTRAINT tags_change_id_fkey FOREIGN KEY (change_id) REFERENCES changes(change_id) ON UPDATE CASCADE;


--
-- Name: tags_project_fkey; Type: FK CONSTRAINT; Schema: sqitch; Owner: postgres
--

ALTER TABLE ONLY tags
    ADD CONSTRAINT tags_project_fkey FOREIGN KEY (project) REFERENCES projects(project) ON UPDATE CASCADE;


--
-- Name: public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM postgres;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--

