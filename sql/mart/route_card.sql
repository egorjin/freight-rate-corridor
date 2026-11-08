-- Monthly route card.
-- Grain: price month x origin x destination x body group x weight category.
-- Month comes from price_dates, not from loading_date, because a long order
-- is expanded across months in the source.
-- volume_category is not part of the grain: one cell mixes FTL and OTH volume,
-- and a single "mode" value would pretend the cell is cleaner than it is.
-- MoM / YoY join the exact calendar neighbour. A missing month stays NULL;
-- we do not fall back to the last month that happens to exist.
-- A cell is HIGH only when the latest trip inside that cell is within 30 days
-- of the snapshot. An old busy month stays MEDIUM: that row is not a live quote.

INSERT INTO mart.route_card (
    price_month,
    loading_city_gcid,
    unloading_city_gcid,
    loading_city,
    unloading_city,
    loading_region,
    unloading_region,
    body_group,
    weight_category,
    trips_count,
    carriers_count,
    p25_trip,
    median_trip,
    p75_trip,
    avg_trip,
    p25_km,
    median_km,
    p75_km,
    cv_rate,
    mom_pct,
    yoy_pct,
    max_price_date,
    reliability_level,
    as_of_date
)
WITH params AS (
    SELECT %(as_of)s::date AS as_of
),
linked AS MATERIALIZED (
    SELECT pbt.price_id, pbt.body_type_id
    FROM public.price_body_types pbt
    JOIN core.prices p ON p.price_id = pbt.price_id
),
fallback AS (
    SELECT p.price_id, p.body_type AS body_type_id
    FROM core.prices p
    WHERE NOT EXISTS (
        SELECT 1 FROM linked l WHERE l.price_id = p.price_id
    )
),
body_links AS (
    -- One price can sit in two groups (tent + board). It must not sit twice
    -- in the same group when 1C stored both the parent and a child code.
    SELECT DISTINCT
        u.price_id,
        coalesce(core.body_group_name(u.body_type_id), 'Не указан') AS body_group
    FROM (
        SELECT price_id, body_type_id FROM linked
        UNION ALL
        SELECT price_id, body_type_id FROM fallback
    ) u
),
scoped AS (
    SELECT
        date_trunc('month', d.price_date)::date AS price_month,
        p.price_id,
        p.loading_city_gcid,
        p.unloading_city_gcid,
        b.body_group,
        p.weight_category,
        p.price_rub,
        p.price_rub / p.distance AS price_km,
        p.organization_id,
        p.price_type,
        d.price_date
    FROM core.prices p
    JOIN body_links b ON b.price_id = p.price_id
    JOIN public.price_dates d ON d.price_id = p.price_id
    CROSS JOIN params
    WHERE p.is_fact
      AND NOT p.complex
      AND NOT p.outlier_mark
      AND p.price > 0
      AND p.price_rub > 0
      AND p.distance > 0
      AND d.price_date <= params.as_of
),
one_per_month AS (
    SELECT DISTINCT ON (price_id, price_month, body_group)
        price_month,
        price_id,
        loading_city_gcid,
        unloading_city_gcid,
        body_group,
        weight_category,
        price_rub,
        price_km,
        organization_id,
        price_type,
        price_date
    FROM scoped
    ORDER BY price_id, price_month, body_group, price_date
),
monthly AS MATERIALIZED (
    SELECT
        price_month,
        loading_city_gcid,
        unloading_city_gcid,
        body_group,
        weight_category,
        count(*)::int AS trips_count,
        count(DISTINCT organization_id) FILTER (WHERE price_type IN (3, 9))::int AS carriers_count,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY price_rub) AS p25_trip,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY price_rub) AS median_trip,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY price_rub) AS p75_trip,
        avg(price_rub) AS avg_trip,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY price_km) AS p25_km,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY price_km) AS median_km,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY price_km) AS p75_km,
        CASE
            WHEN count(*) < 2 OR avg(price_rub) = 0 THEN NULL
            ELSE stddev_samp(price_rub) / avg(price_rub)
        END AS cv_rate,
        max(price_date) AS max_price_date
    FROM one_per_month
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    m.price_month,
    m.loading_city_gcid,
    m.unloading_city_gcid,
    lc.city_name,
    uc.city_name,
    lc.region_name,
    uc.region_name,
    m.body_group,
    m.weight_category,
    m.trips_count,
    m.carriers_count,
    m.p25_trip,
    m.median_trip,
    m.p75_trip,
    m.avg_trip,
    m.p25_km,
    m.median_km,
    m.p75_km,
    m.cv_rate,
    CASE
        WHEN prev.median_trip IS NULL OR prev.median_trip = 0 THEN NULL
        ELSE (m.median_trip - prev.median_trip) / prev.median_trip * 100
    END AS mom_pct,
    CASE
        WHEN prev_year.median_trip IS NULL OR prev_year.median_trip = 0 THEN NULL
        ELSE (m.median_trip - prev_year.median_trip) / prev_year.median_trip * 100
    END AS yoy_pct,
    m.max_price_date,
    CASE
        WHEN m.trips_count >= 30
         AND m.carriers_count >= 5
         AND (params.as_of - m.max_price_date) <= 30
        THEN 'HIGH'
        WHEN m.trips_count >= 10 THEN 'MEDIUM'
        ELSE 'LOW_DATA'
    END AS reliability_level,
    params.as_of
FROM monthly m
JOIN core.dim_cities lc ON lc.gc_id = m.loading_city_gcid
JOIN core.dim_cities uc ON uc.gc_id = m.unloading_city_gcid
LEFT JOIN monthly prev
    ON prev.loading_city_gcid = m.loading_city_gcid
   AND prev.unloading_city_gcid = m.unloading_city_gcid
   AND prev.body_group = m.body_group
   AND prev.weight_category = m.weight_category
   AND prev.price_month = (m.price_month - interval '1 month')::date
LEFT JOIN monthly prev_year
    ON prev_year.loading_city_gcid = m.loading_city_gcid
   AND prev_year.unloading_city_gcid = m.unloading_city_gcid
   AND prev_year.body_group = m.body_group
   AND prev_year.weight_category = m.weight_category
   AND prev_year.price_month = (m.price_month - interval '1 year')::date
CROSS JOIN params;
