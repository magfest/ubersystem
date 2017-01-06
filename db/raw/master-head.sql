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
-- Name: admin_account; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE admin_account (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    hashed character varying DEFAULT ''::character varying NOT NULL,
    access character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.admin_account OWNER TO rams_db;

--
-- Name: approved_email; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE approved_email (
    id uuid NOT NULL,
    subject character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.approved_email OWNER TO rams_db;

--
-- Name: arbitrary_charge; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE arbitrary_charge (
    id uuid NOT NULL,
    amount integer NOT NULL,
    what character varying DEFAULT ''::character varying NOT NULL,
    "when" timestamp without time zone NOT NULL,
    reg_station integer
);


ALTER TABLE public.arbitrary_charge OWNER TO rams_db;

--
-- Name: attendee; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE attendee (
    id uuid NOT NULL,
    watchlist_id uuid,
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
    can_work_teardown boolean DEFAULT false NOT NULL,
    extra_donation integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.attendee OWNER TO rams_db;

--
-- Name: dept_checklist_item; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE dept_checklist_item (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    slug character varying DEFAULT ''::character varying NOT NULL,
    comments character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.dept_checklist_item OWNER TO rams_db;

--
-- Name: email; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
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


ALTER TABLE public.email OWNER TO rams_db;

--
-- Name: food_restrictions; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE food_restrictions (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    standard character varying DEFAULT ''::character varying NOT NULL,
    sandwich_pref character varying DEFAULT ''::character varying NOT NULL,
    freeform character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.food_restrictions OWNER TO rams_db;

--
-- Name: group; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
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


ALTER TABLE public."group" OWNER TO rams_db;

--
-- Name: job; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
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


ALTER TABLE public.job OWNER TO rams_db;

--
-- Name: m_points_for_cash; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE m_points_for_cash (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    amount integer NOT NULL,
    "when" timestamp without time zone NOT NULL
);


ALTER TABLE public.m_points_for_cash OWNER TO rams_db;

--
-- Name: merch_pickup; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE merch_pickup (
    id uuid NOT NULL,
    picked_up_by_id uuid NOT NULL,
    picked_up_for_id uuid NOT NULL
);


ALTER TABLE public.merch_pickup OWNER TO rams_db;

--
-- Name: no_shirt; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE no_shirt (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL
);


ALTER TABLE public.no_shirt OWNER TO rams_db;

--
-- Name: old_m_point_exchange; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE old_m_point_exchange (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    amount integer NOT NULL,
    "when" timestamp without time zone NOT NULL
);


ALTER TABLE public.old_m_point_exchange OWNER TO rams_db;

--
-- Name: password_reset; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE password_reset (
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    generated timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    hashed character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.password_reset OWNER TO rams_db;

--
-- Name: sale; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
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


ALTER TABLE public.sale OWNER TO rams_db;

--
-- Name: shift; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE shift (
    id uuid NOT NULL,
    job_id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    worked integer DEFAULT 176686787 NOT NULL,
    rating integer DEFAULT 54944008 NOT NULL,
    comment character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.shift OWNER TO rams_db;

--
-- Name: tracking; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
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


ALTER TABLE public.tracking OWNER TO rams_db;

--
-- Name: watch_list; Type: TABLE; Schema: public; Owner: rams_db; Tablespace: 
--

CREATE TABLE watch_list (
    id uuid NOT NULL,
    first_names character varying DEFAULT ''::character varying NOT NULL,
    last_name character varying DEFAULT ''::character varying NOT NULL,
    email character varying DEFAULT ''::character varying NOT NULL,
    birthdate date,
    reason character varying DEFAULT ''::character varying NOT NULL,
    action character varying DEFAULT ''::character varying NOT NULL,
    active boolean DEFAULT true NOT NULL
);


ALTER TABLE public.watch_list OWNER TO rams_db;

--
-- Name: _dept_checklist_item_uniq; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT _dept_checklist_item_uniq UNIQUE (attendee_id, slug);


--
-- Name: admin_account_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_attendee_id_key UNIQUE (attendee_id);


--
-- Name: admin_account_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_pkey PRIMARY KEY (id);


--
-- Name: approved_email_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY approved_email
    ADD CONSTRAINT approved_email_pkey PRIMARY KEY (id);


--
-- Name: arbitrary_charge_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY arbitrary_charge
    ADD CONSTRAINT arbitrary_charge_pkey PRIMARY KEY (id);


--
-- Name: attendee_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_pkey PRIMARY KEY (id);


--
-- Name: attendee_watchlist_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_watchlist_id_key UNIQUE (watchlist_id);


--
-- Name: dept_checklist_item_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT dept_checklist_item_pkey PRIMARY KEY (id);


--
-- Name: email_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY email
    ADD CONSTRAINT email_pkey PRIMARY KEY (id);


--
-- Name: food_restrictions_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_attendee_id_key UNIQUE (attendee_id);


--
-- Name: food_restrictions_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_pkey PRIMARY KEY (id);


--
-- Name: group_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY "group"
    ADD CONSTRAINT group_pkey PRIMARY KEY (id);


--
-- Name: job_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY job
    ADD CONSTRAINT job_pkey PRIMARY KEY (id);


--
-- Name: m_points_for_cash_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY m_points_for_cash
    ADD CONSTRAINT m_points_for_cash_pkey PRIMARY KEY (id);


--
-- Name: merch_pickup_picked_up_for_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_for_id_key UNIQUE (picked_up_for_id);


--
-- Name: merch_pickup_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_pkey PRIMARY KEY (id);


--
-- Name: no_shirt_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_attendee_id_key UNIQUE (attendee_id);


--
-- Name: no_shirt_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_pkey PRIMARY KEY (id);


--
-- Name: old_m_point_exchange_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY old_m_point_exchange
    ADD CONSTRAINT old_m_point_exchange_pkey PRIMARY KEY (id);


--
-- Name: password_reset_account_id_key; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_account_id_key UNIQUE (account_id);


--
-- Name: password_reset_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_pkey PRIMARY KEY (id);


--
-- Name: sale_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY sale
    ADD CONSTRAINT sale_pkey PRIMARY KEY (id);


--
-- Name: shift_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_pkey PRIMARY KEY (id);


--
-- Name: tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY tracking
    ADD CONSTRAINT tracking_pkey PRIMARY KEY (id);


--
-- Name: watch_list_pkey; Type: CONSTRAINT; Schema: public; Owner: rams_db; Tablespace: 
--

ALTER TABLE ONLY watch_list
    ADD CONSTRAINT watch_list_pkey PRIMARY KEY (id);


--
-- Name: admin_account_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: attendee_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_group_id_fkey FOREIGN KEY (group_id) REFERENCES "group"(id) ON DELETE SET NULL;


--
-- Name: attendee_watchlist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY attendee
    ADD CONSTRAINT attendee_watchlist_id_fkey FOREIGN KEY (watchlist_id) REFERENCES watch_list(id) ON DELETE SET NULL;


--
-- Name: dept_checklist_item_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY dept_checklist_item
    ADD CONSTRAINT dept_checklist_item_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: fk_leader; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY "group"
    ADD CONSTRAINT fk_leader FOREIGN KEY (leader_id) REFERENCES attendee(id);


--
-- Name: food_restrictions_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY food_restrictions
    ADD CONSTRAINT food_restrictions_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: m_points_for_cash_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY m_points_for_cash
    ADD CONSTRAINT m_points_for_cash_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: merch_pickup_picked_up_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_by_id_fkey FOREIGN KEY (picked_up_by_id) REFERENCES attendee(id);


--
-- Name: merch_pickup_picked_up_for_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY merch_pickup
    ADD CONSTRAINT merch_pickup_picked_up_for_id_fkey FOREIGN KEY (picked_up_for_id) REFERENCES attendee(id);


--
-- Name: no_shirt_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY no_shirt
    ADD CONSTRAINT no_shirt_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: old_m_point_exchange_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY old_m_point_exchange
    ADD CONSTRAINT old_m_point_exchange_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: password_reset_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY password_reset
    ADD CONSTRAINT password_reset_account_id_fkey FOREIGN KEY (account_id) REFERENCES admin_account(id);


--
-- Name: sale_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY sale
    ADD CONSTRAINT sale_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE SET NULL;


--
-- Name: shift_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE CASCADE;


--
-- Name: shift_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: rams_db
--

ALTER TABLE ONLY shift
    ADD CONSTRAINT shift_job_id_fkey FOREIGN KEY (job_id) REFERENCES job(id) ON DELETE CASCADE;


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

