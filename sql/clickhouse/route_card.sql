-- Copy of mart.route_card. The grain matches the Postgres primary key.
-- ReplacingMergeTree keeps the newest built_at when a run is repeated.
-- Read with FINAL, or the previous copy can still be visible.

CREATE DATABASE IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS mart.route_card
(
    price_month           Date,
    loading_city_gcid     Int32,
    unloading_city_gcid   Int32,
    loading_city          Nullable(String),
    unloading_city        Nullable(String),
    loading_region        Nullable(String),
    unloading_region      Nullable(String),
    body_group            String,
    weight_category       String,
    trips_count           Int32,
    carriers_count        Int32,
    p25_trip              Nullable(Float64),
    median_trip           Nullable(Float64),
    p75_trip              Nullable(Float64),
    avg_trip              Nullable(Float64),
    p25_km                Nullable(Float64),
    median_km             Nullable(Float64),
    p75_km                Nullable(Float64),
    cv_rate               Nullable(Float64),
    mom_pct               Nullable(Float64),
    yoy_pct               Nullable(Float64),
    max_price_date        Nullable(Date),
    reliability_level     String,
    as_of_date            Date,
    built_at              DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree(built_at)
ORDER BY (
    price_month,
    loading_city_gcid,
    unloading_city_gcid,
    body_group,
    weight_category
);
