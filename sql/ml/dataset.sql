-- Rows the model is allowed to see.
-- price_rub is the target, not a feature. price_group_stats is not joined:
-- that table is an aggregate of the raw price and can include the row itself.
-- outlier_mark is selected only so the loader can drop marked rows. It is not
-- passed into CatBoost.
-- One row per price. The mart may count the same price in two body groups;
-- the model needs a single body, taken from prices.body_type, then from the
-- linked 1C types if the price itself has none.

SELECT
    p.price_id,
    p.loading_date,
    p.loading_city_gcid,
    p.unloading_city_gcid,
    p.distance,
    p.total_weight,
    p.total_volume,
    p.body_type,
    coalesce(
        core.body_group_name(p.body_type),
        (
            SELECT core.body_group_name(min(pbt.body_type_id))
            FROM public.price_body_types pbt
            WHERE pbt.price_id = p.price_id
        ),
        'Не указан'
    ) AS body_group,
    p.weight_category,
    p.volume_category,
    p.price_rub,
    p.is_fact,
    p.complex,
    p.outlier_mark,
    lc.city_name AS origin_city,
    lc.region_name AS origin_region,
    lc.latitude AS origin_lat,
    lc.longitude AS origin_lon,
    uc.city_name AS dest_city,
    uc.region_name AS dest_region,
    uc.latitude AS dest_lat,
    uc.longitude AS dest_lon
FROM core.prices p
JOIN core.dim_cities lc ON lc.gc_id = p.loading_city_gcid
JOIN core.dim_cities uc ON uc.gc_id = p.unloading_city_gcid
WHERE p.distance > 0
  AND p.price_rub > 0
  AND p.is_fact
  AND NOT p.complex
  AND NOT p.outlier_mark
  AND (
        (p.loading_date >= %(train_start)s AND p.loading_date <= %(as_of)s)
        OR p.loading_date > %(as_of)s
      );
