CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS mart.route_card (
    price_month           date NOT NULL,
    loading_city_gcid     integer NOT NULL,
    unloading_city_gcid   integer NOT NULL,
    loading_city          text,
    unloading_city        text,
    loading_region        text,
    unloading_region      text,
    body_group            text NOT NULL,
    weight_category       varchar(4) NOT NULL,
    trips_count           integer NOT NULL,
    carriers_count        integer NOT NULL,
    p25_trip              double precision,
    median_trip           double precision,
    p75_trip              double precision,
    avg_trip              double precision,
    p25_km                double precision,
    median_km             double precision,
    p75_km                double precision,
    cv_rate               double precision,
    mom_pct               double precision,
    yoy_pct               double precision,
    max_price_date        date,
    reliability_level     text NOT NULL,
    as_of_date            date NOT NULL,
    built_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        price_month,
        loading_city_gcid,
        unloading_city_gcid,
        body_group,
        weight_category
    )
);

CREATE INDEX IF NOT EXISTS route_card_direction_idx
    ON mart.route_card (
        loading_city_gcid,
        unloading_city_gcid,
        body_group,
        weight_category,
        price_month
    );

CREATE TABLE IF NOT EXISTS mart.ml_price_predictions (
    price_id              bigint PRIMARY KEY,
    loading_date          date NOT NULL,
    loading_city_gcid     integer NOT NULL,
    unloading_city_gcid   integer NOT NULL,
    body_group            text,
    actual_price_rub      double precision,
    predicted_price_rub   double precision NOT NULL,
    abs_error_rub         double precision,
    ape_pct               double precision,
    model_name            text NOT NULL,
    scored_at             timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ml_predictions_loading_date_idx
    ON mart.ml_price_predictions (loading_date);

CREATE TABLE IF NOT EXISTS mart.ml_run_metrics (
    model_name    text PRIMARY KEY,
    train_rows    integer NOT NULL,
    test_rows     integer NOT NULL,
    r2            double precision,
    mape_pct      double precision,
    rmse_rub      double precision,
    mae_rub       double precision,
    trained_at    timestamptz NOT NULL
);
