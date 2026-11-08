-- Spot checks after pipeline.py. None of these are part of the load.

-- quarantine mix
select reason, count(*)
from core.dq_quarantine_prices
group by 1
order by 2 desc;

-- Moscow -> Kazan, tent, FTL. The card a procurement lead actually opens.
select price_month,
       trips_count,
       carriers_count,
       reliability_level,
       round(p25_trip::numeric) as p25_trip,
       round(median_trip::numeric) as median_trip,
       round(p75_trip::numeric) as p75_trip,
       round(median_km::numeric, 2) as median_km,
       round(mom_pct::numeric, 1) as mom_pct,
       round(yoy_pct::numeric, 1) as yoy_pct
from mart.route_card
where loading_city_gcid = 1001
  and unloading_city_gcid = 1003
  and body_group = 'Тент'
  and weight_category = 'FTL'
order by price_month;

-- a duplicated gc_id must not fan out the city dim
select gc_id, count(*)
from core.dim_cities
group by 1
having count(*) > 1;

-- one price, one prediction
select count(*) as predictions, count(distinct price_id) as prices
from mart.ml_price_predictions;

-- future loads keep the price in the source, but the comparison columns are empty
select count(*) as future_rows,
       count(actual_price_rub) as actuals_filled
from mart.ml_price_predictions
where loading_date > date '2026-10-26';

-- test window: actual is filled
select count(*) as test_rows,
       round(avg(ape_pct)::numeric, 2) as avg_ape
from mart.ml_price_predictions
where loading_date between date '2026-10-05' and date '2026-10-26';

select model_name, train_rows, test_rows,
       round(r2::numeric, 4) as r2,
       round(mape_pct::numeric, 2) as mape_pct,
       round(rmse_rub::numeric) as rmse_rub,
       round(mae_rub::numeric) as mae_rub
from mart.ml_run_metrics
order by model_name;
