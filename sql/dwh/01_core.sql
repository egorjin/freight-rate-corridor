-- Core layer. Source tables stay in public; this schema is the cleaned copy.

CREATE SCHEMA IF NOT EXISTS core;

-- NULL in, NULL out. The mart and the model label a missing body as "Не указан".
CREATE OR REPLACE FUNCTION core.body_group_name(body_type_id integer)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN body_type_id IS NULL THEN NULL
    WHEN body_type_id IN (56, 57, 58, 59, 60, 61) THEN 'Тент'
    WHEN body_type_id IN (4, 46, 47, 48) THEN 'Рефрижератор'
    WHEN body_type_id = 2 THEN 'Изотерм'
    WHEN body_type_id IN (1, 15) THEN 'Борт'
    ELSE 'Прочие'
  END
$$;

CREATE TABLE IF NOT EXISTS core.dim_cities (
    gc_id           integer PRIMARY KEY,
    city_id         bigint NOT NULL,
    city_name       text NOT NULL,
    region_name     text,
    full_name_local text NOT NULL,
    latitude        double precision,
    longitude       double precision
);

CREATE TABLE IF NOT EXISTS core.prices (
    price_id              bigint PRIMARY KEY,
    loading_date          date NOT NULL,
    end_loading_date      date,
    loading_city_gcid     integer NOT NULL,
    unloading_city_gcid   integer NOT NULL,
    distance              double precision NOT NULL,
    total_weight          double precision NOT NULL,
    total_volume          double precision NOT NULL,
    body_type             integer,
    price                 double precision NOT NULL,
    currency_code         varchar(3) NOT NULL,
    fx_rate               double precision NOT NULL,
    fx_rate_date          date,
    price_rub             double precision NOT NULL,
    complex               boolean NOT NULL,
    price_type            smallint NOT NULL,
    is_fact               boolean NOT NULL,
    organization_id       integer,
    subscriber_id         integer,
    outlier_mark          boolean NOT NULL,
    weight_category       varchar(4) NOT NULL,
    volume_category       varchar(4) NOT NULL,
    created_at            timestamp,
    loaded_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS core_prices_loading_date_idx
    ON core.prices (loading_date);

CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
    price_id              bigint PRIMARY KEY,
    loading_date          date NOT NULL,
    reason                text NOT NULL,
    price                 double precision,
    currency_code         varchar(3),
    distance              double precision,
    total_weight          double precision,
    total_volume          double precision,
    loading_city_gcid     integer,
    unloading_city_gcid   integer,
    nearest_rate_date     date,
    quarantined_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dq_quarantine_reason_idx
    ON core.dq_quarantine_prices (reason);
