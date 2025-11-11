--
-- PostgreSQL database dump
--

\restrict g7f5gcr6FoWn2iJIniYyRljSqhiYJRStKO8v8iCwCFblPvR8ULdqHGceiyeoumV

-- Dumped from database version 17.6 (Debian 17.6-2.pgdg13+1)
-- Dumped by pg_dump version 17.6 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ 
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alerts (
    id integer NOT NULL,
    uuid text NOT NULL,
    title text,
    summary text,
    link text,
    source text,
    published timestamp without time zone,
    region text,
    country text,
    city text,
    latitude numeric,
    longitude numeric,
    category text,
    subcategory text,
    score text,
    label text,
    confidence text,
    domains jsonb DEFAULT '[]'::jsonb,
    sources jsonb DEFAULT '[]'::jsonb,
    baseline_ratio numeric,
    trend_direction text,
    incident_count_30d integer DEFAULT 0,
    anomaly_flag boolean DEFAULT false,
    future_risk_probability text,
    cluster_id text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    gpt_summary text,
    en_snippet text,
    language text,
    kw_match jsonb DEFAULT '[]'::jsonb,
    sentiment text,
    threat_type text,
    threat_level text,
    threat_label text,
    reasoning text,
    forecast text,
    legal_risk text,
    cyber_ot_risk text,
    environmental_epidemic_risk text,
    trend_score text,
    trend_score_msg text,
    is_anomaly boolean DEFAULT false,
    early_warning_indicators jsonb DEFAULT '[]'::jsonb,
    series_id text,
    incident_series text,
    historical_context text,
    recent_count_7d integer DEFAULT 0,
    baseline_avg_7d numeric,
    reports_analyzed integer DEFAULT 1,
    category_confidence double precision,
    review_flag boolean DEFAULT false,
    review_notes text,
    ingested_at timestamp without time zone DEFAULT now(),
    model_used text,
    keyword_weight text,
    tags text[]
);


ALTER TABLE public.alerts OWNER TO postgres;

--
-- Name: alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alerts_id_seq OWNER TO postgres;

--
-- Name: alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;


--
-- Name: email_alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.email_alerts (
    id integer NOT NULL,
    email text NOT NULL,
    alert_id integer,
    sent_at timestamp without time zone DEFAULT now(),
    status text DEFAULT 'sent'::text
);


ALTER TABLE public.email_alerts OWNER TO postgres;

--
-- Name: email_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.email_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.email_alerts_id_seq OWNER TO postgres;

--
-- Name: email_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.email_alerts_id_seq OWNED BY public.email_alerts.id;


--
-- Name: email_verification_codes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.email_verification_codes (
    email text NOT NULL,
    code text NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    attempts integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.email_verification_codes OWNER TO postgres;

--
-- Name: email_verification_ip_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.email_verification_ip_log (
    id integer NOT NULL,
    ip text NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.email_verification_ip_log OWNER TO postgres;

--
-- Name: email_verification_ip_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.email_verification_ip_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.email_verification_ip_log_id_seq OWNER TO postgres;

--
-- Name: email_verification_ip_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.email_verification_ip_log_id_seq OWNED BY public.email_verification_ip_log.id;


--
-- Name: feed_health; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.feed_health (
    id integer NOT NULL,
    feed_url text NOT NULL,
    host text,
    last_status integer,
    last_error text,
    last_ok timestamp without time zone,
    last_checked timestamp without time zone DEFAULT now(),
    ok_count integer DEFAULT 0,
    error_count integer DEFAULT 0,
    avg_latency_ms numeric,
    consecutive_fail integer DEFAULT 0,
    backoff_until timestamp without time zone
);


ALTER TABLE public.feed_health OWNER TO postgres;

--
-- Name: feed_health_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.feed_health_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feed_health_id_seq OWNER TO postgres;

--
-- Name: feed_health_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.feed_health_id_seq OWNED BY public.feed_health.id;


--
-- Name: geocode_cache; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.geocode_cache (
    id integer NOT NULL,
    city text NOT NULL,
    country text,
    lat numeric,
    lon numeric,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.geocode_cache OWNER TO postgres;

--
-- Name: geocode_cache_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.geocode_cache_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.geocode_cache_id_seq OWNER TO postgres;

--
-- Name: geocode_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.geocode_cache_id_seq OWNED BY public.geocode_cache.id;


--
-- Name: plans; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.plans (
    name text NOT NULL,
    price_cents integer NOT NULL,
    chat_messages_per_month integer NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.plans OWNER TO postgres;

--
-- Name: raw_alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.raw_alerts (
    id integer NOT NULL,
    uuid text NOT NULL,
    title text,
    summary text,
    en_snippet text,
    link text,
    source text,
    published timestamp without time zone,
    tags jsonb DEFAULT '[]'::jsonb,
    region text,
    country text,
    city text,
    language text,
    latitude numeric,
    longitude numeric,
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    gpt_summary text,
    kw_match jsonb DEFAULT '[]'::jsonb,
    ingested_at timestamp without time zone DEFAULT now(),
    source_tag text,
    source_kind text,
    source_priority integer
);


ALTER TABLE public.raw_alerts OWNER TO postgres;

--
-- Name: raw_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.raw_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.raw_alerts_id_seq OWNER TO postgres;

--
-- Name: raw_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.raw_alerts_id_seq OWNED BY public.raw_alerts.id;


--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.refresh_tokens (
    refresh_id text NOT NULL,
    email text NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.refresh_tokens OWNER TO postgres;

--
-- Name: region_trends; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.region_trends (
    id integer NOT NULL,
    region text,
    city text,
    window_start timestamp without time zone,
    window_end timestamp without time zone,
    trend_score numeric,
    top_threats text[],
    summary text,
    created_at timestamp without time zone DEFAULT now(),
    incident_count integer DEFAULT 0,
    categories text[],
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.region_trends OWNER TO postgres;

--
-- Name: region_trends_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.region_trends_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.region_trends_id_seq OWNER TO postgres;

--
-- Name: region_trends_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.region_trends_id_seq OWNED BY public.region_trends.id;


--
-- Name: security_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.security_events (
    id integer NOT NULL,
    event_type text NOT NULL,
    email text,
    ip_address text,
    user_agent text,
    endpoint text,
    details text,
    created_at timestamp without time zone DEFAULT now(),
    ip text,
    plan text
);


ALTER TABLE public.security_events OWNER TO postgres;

--
-- Name: security_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.security_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.security_events_id_seq OWNER TO postgres;

--
-- Name: security_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.security_events_id_seq OWNED BY public.security_events.id;


--
-- Name: user_usage; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_usage (
    user_id integer NOT NULL,
    chat_messages_used integer DEFAULT 0,
    chat_messages_limit integer DEFAULT 3,
    last_reset timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    email text,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_usage OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    plan text DEFAULT 'FREE'::text,
    name text,
    employer text,
    email_verified boolean DEFAULT false,
    is_active boolean DEFAULT true,
    preferred_region text,
    preferred_threat_type text,
    home_location text,
    extra_details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: alerts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);


--
-- Name: email_alerts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_alerts ALTER COLUMN id SET DEFAULT nextval('public.email_alerts_id_seq'::regclass);


--
-- Name: email_verification_ip_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_verification_ip_log ALTER COLUMN id SET DEFAULT nextval('public.email_verification_ip_log_id_seq'::regclass);


--
-- Name: feed_health id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feed_health ALTER COLUMN id SET DEFAULT nextval('public.feed_health_id_seq'::regclass);


--
-- Name: geocode_cache id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.geocode_cache ALTER COLUMN id SET DEFAULT nextval('public.geocode_cache_id_seq'::regclass);


--
-- Name: raw_alerts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.raw_alerts ALTER COLUMN id SET DEFAULT nextval('public.raw_alerts_id_seq'::regclass);


--
-- Name: region_trends id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region_trends ALTER COLUMN id SET DEFAULT nextval('public.region_trends_id_seq'::regclass);


--
-- Name: security_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_events ALTER COLUMN id SET DEFAULT nextval('public.security_events_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: alerts alerts_uuid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_uuid_key UNIQUE (uuid);


--
-- Name: email_alerts email_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_alerts
    ADD CONSTRAINT email_alerts_pkey PRIMARY KEY (id);


--
-- Name: email_verification_codes email_verification_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_verification_codes
    ADD CONSTRAINT email_verification_codes_pkey PRIMARY KEY (email);


--
-- Name: email_verification_ip_log email_verification_ip_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_verification_ip_log
    ADD CONSTRAINT email_verification_ip_log_pkey PRIMARY KEY (id);


--
-- Name: feed_health feed_health_feed_url_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feed_health
    ADD CONSTRAINT feed_health_feed_url_key UNIQUE (feed_url);


--
-- Name: feed_health feed_health_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feed_health
    ADD CONSTRAINT feed_health_pkey PRIMARY KEY (id);


--
-- Name: geocode_cache geocode_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.geocode_cache
    ADD CONSTRAINT geocode_cache_pkey PRIMARY KEY (id);


--
-- Name: plans plans_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT plans_pkey PRIMARY KEY (name);


--
-- Name: raw_alerts raw_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.raw_alerts
    ADD CONSTRAINT raw_alerts_pkey PRIMARY KEY (id);


--
-- Name: raw_alerts raw_alerts_uuid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.raw_alerts
    ADD CONSTRAINT raw_alerts_uuid_key UNIQUE (uuid);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (refresh_id);


--
-- Name: region_trends region_trends_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region_trends
    ADD CONSTRAINT region_trends_pkey PRIMARY KEY (id);


--
-- Name: region_trends region_trends_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region_trends
    ADD CONSTRAINT region_trends_unique UNIQUE (region, city, window_start, window_end);


--
-- Name: security_events security_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_events
    ADD CONSTRAINT security_events_pkey PRIMARY KEY (id);


--
-- Name: user_usage user_usage_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_usage
    ADD CONSTRAINT user_usage_email_key UNIQUE (email);


--
-- Name: user_usage user_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_usage
    ADD CONSTRAINT user_usage_pkey PRIMARY KEY (user_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_alerts_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_category ON public.alerts USING btree (category);


--
-- Name: idx_alerts_city; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_city ON public.alerts USING btree (city);


--
-- Name: idx_alerts_country; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_country ON public.alerts USING btree (country);


--
-- Name: idx_alerts_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_created ON public.alerts USING btree (created_at);


--
-- Name: idx_alerts_ingested_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_ingested_at ON public.alerts USING btree (ingested_at);


--
-- Name: idx_alerts_published; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_published ON public.alerts USING btree (published);


--
-- Name: idx_alerts_region_country; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_region_country ON public.alerts USING btree (region, country);


--
-- Name: idx_alerts_score; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_score ON public.alerts USING btree (score);


--
-- Name: idx_alerts_tags; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_tags ON public.alerts USING gin (tags);


--
-- Name: idx_alerts_uuid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_uuid ON public.alerts USING btree (uuid);


--
-- Name: idx_email_alerts_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_email_alerts_email ON public.email_alerts USING btree (email);


--
-- Name: idx_email_alerts_sent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_email_alerts_sent ON public.email_alerts USING btree (sent_at);


--
-- Name: idx_feed_health_host; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_feed_health_host ON public.feed_health USING btree (host);


--
-- Name: idx_feed_health_url; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_feed_health_url ON public.feed_health USING btree (feed_url);


--
-- Name: idx_geocode_city_country; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_geocode_city_country ON public.geocode_cache USING btree (city, country);


--
-- Name: idx_raw_alerts_city; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_alerts_city ON public.raw_alerts USING btree (city);


--
-- Name: idx_raw_alerts_country; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_alerts_country ON public.raw_alerts USING btree (country);


--
-- Name: idx_raw_alerts_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_alerts_created ON public.raw_alerts USING btree (created_at);


--
-- Name: idx_raw_alerts_published; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_alerts_published ON public.raw_alerts USING btree (published);


--
-- Name: idx_raw_alerts_uuid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_alerts_uuid ON public.raw_alerts USING btree (uuid);


--
-- Name: idx_refresh_tokens_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_refresh_tokens_email ON public.refresh_tokens USING btree (email);


--
-- Name: idx_region_trends_region_city_window; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_region_trends_region_city_window ON public.region_trends USING btree (region, city, window_start, window_end);


--
-- Name: idx_security_events_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_events_created ON public.security_events USING btree (created_at);


--
-- Name: idx_security_events_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_events_email ON public.security_events USING btree (email);


--
-- Name: idx_user_usage_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_usage_email ON public.user_usage USING btree (email);


--
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- Name: idx_users_plan; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_users_plan ON public.users USING btree (plan);


--
-- Name: alerts update_alerts_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON public.alerts FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_usage update_user_usage_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_user_usage_updated_at BEFORE UPDATE ON public.user_usage FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: users update_users_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: email_alerts email_alerts_alert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.email_alerts
    ADD CONSTRAINT email_alerts_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(id) ON DELETE CASCADE;


--
-- Name: user_usage user_usage_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_usage
    ADD CONSTRAINT user_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_plan_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_plan_fkey FOREIGN KEY (plan) REFERENCES public.plans(name);


--
-- PostgreSQL database dump complete
--

\unrestrict g7f5gcr6FoWn2iJIniYyRljSqhiYJRStKO8v8iCwCFblPvR8ULdqHGceiyeoumV

