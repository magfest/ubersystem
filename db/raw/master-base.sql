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
-- Name: assigned_panelist; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE assigned_panelist (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    event_id uuid NOT NULL
);


ALTER TABLE public.assigned_panelist OWNER TO m13;

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
    fire_safety_cert character varying DEFAULT ''::character varying NOT NULL,
    requested_depts character varying DEFAULT ''::character varying NOT NULL,
    assigned_depts character varying DEFAULT ''::character varying NOT NULL,
    trusted boolean DEFAULT false NOT NULL,
    nonshift_hours integer DEFAULT 0 NOT NULL,
    past_years character varying DEFAULT ''::character varying NOT NULL
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
-- Name: event; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE event (
    id uuid NOT NULL,
    location integer NOT NULL,
    start_time timestamp without time zone NOT NULL,
    duration integer NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    description character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.event OWNER TO m13;

--
-- Name: food_restrictions; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE food_restrictions (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    standard character varying DEFAULT ''::character varying NOT NULL,
    sandwich_pref integer NOT NULL,
    no_cheese boolean DEFAULT false NOT NULL,
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
-- Name: hotel_requests; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE hotel_requests (
    id uuid NOT NULL,
    attendee_id uuid NOT NULL,
    nights character varying DEFAULT ''::character varying NOT NULL,
    wanted_roommates character varying DEFAULT ''::character varying NOT NULL,
    unwanted_roommates character varying DEFAULT ''::character varying NOT NULL,
    special_needs character varying DEFAULT ''::character varying NOT NULL,
    approved boolean DEFAULT false NOT NULL
);


ALTER TABLE public.hotel_requests OWNER TO m13;

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
-- Name: prev_season_supporter; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE prev_season_supporter (
    id uuid NOT NULL,
    first_name character varying DEFAULT ''::character varying NOT NULL,
    last_name character varying DEFAULT ''::character varying NOT NULL,
    email character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.prev_season_supporter OWNER TO m13;

--
-- Name: room; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE room (
    id uuid NOT NULL,
    department integer NOT NULL,
    notes character varying DEFAULT ''::character varying NOT NULL,
    nights character varying DEFAULT ''::character varying NOT NULL,
    created timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);


ALTER TABLE public.room OWNER TO m13;

--
-- Name: room_assignment; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE room_assignment (
    id uuid NOT NULL,
    room_id uuid NOT NULL,
    attendee_id uuid NOT NULL
);


ALTER TABLE public.room_assignment OWNER TO m13;

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
-- Name: season_pass_ticket; Type: TABLE; Schema: public; Owner: m13; Tablespace: 
--

CREATE TABLE season_pass_ticket (
    id uuid NOT NULL,
    fk_id uuid NOT NULL,
    slug character varying DEFAULT ''::character varying NOT NULL
);


ALTER TABLE public.season_pass_ticket OWNER TO m13;

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
-- Name: assigned_panelist_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY assigned_panelist
    ADD CONSTRAINT assigned_panelist_pkey PRIMARY KEY (id);


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
-- Name: event_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY event
    ADD CONSTRAINT event_pkey PRIMARY KEY (id);


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
-- Name: hotel_requests_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY hotel_requests
    ADD CONSTRAINT hotel_requests_attendee_id_key UNIQUE (attendee_id);


--
-- Name: hotel_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY hotel_requests
    ADD CONSTRAINT hotel_requests_pkey PRIMARY KEY (id);


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
-- Name: prev_season_supporter_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY prev_season_supporter
    ADD CONSTRAINT prev_season_supporter_pkey PRIMARY KEY (id);


--
-- Name: room_assignment_attendee_id_key; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY room_assignment
    ADD CONSTRAINT room_assignment_attendee_id_key UNIQUE (attendee_id);


--
-- Name: room_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY room_assignment
    ADD CONSTRAINT room_assignment_pkey PRIMARY KEY (id);


--
-- Name: room_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY room
    ADD CONSTRAINT room_pkey PRIMARY KEY (id);


--
-- Name: sale_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY sale
    ADD CONSTRAINT sale_pkey PRIMARY KEY (id);


--
-- Name: season_pass_ticket_pkey; Type: CONSTRAINT; Schema: public; Owner: m13; Tablespace: 
--

ALTER TABLE ONLY season_pass_ticket
    ADD CONSTRAINT season_pass_ticket_pkey PRIMARY KEY (id);


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


--
-- Name: admin_account_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY admin_account
    ADD CONSTRAINT admin_account_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: assigned_panelist_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY assigned_panelist
    ADD CONSTRAINT assigned_panelist_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id) ON DELETE CASCADE;


--
-- Name: assigned_panelist_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY assigned_panelist
    ADD CONSTRAINT assigned_panelist_event_id_fkey FOREIGN KEY (event_id) REFERENCES event(id) ON DELETE CASCADE;


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
-- Name: hotel_requests_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY hotel_requests
    ADD CONSTRAINT hotel_requests_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


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
-- Name: room_assignment_attendee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY room_assignment
    ADD CONSTRAINT room_assignment_attendee_id_fkey FOREIGN KEY (attendee_id) REFERENCES attendee(id);


--
-- Name: room_assignment_room_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: m13
--

ALTER TABLE ONLY room_assignment
    ADD CONSTRAINT room_assignment_room_id_fkey FOREIGN KEY (room_id) REFERENCES room(id);


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

