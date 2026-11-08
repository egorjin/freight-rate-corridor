from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etl.db import iter_statements
from etl.settings import split_bounds
from ml.features import (
    FEATURES,
    LEAKED_COLUMNS,
    add_calendar_features,
    build_prediction_frame,
    model_population,
    prepare_features,
    split_by_loading_date,
)
from ml.metrics import regression_metrics

ROOT = Path(__file__).resolve().parents[1]


def _chord(a, b, period):
    va = np.array([np.sin(2 * np.pi * a / period), np.cos(2 * np.pi * a / period)])
    vb = np.array([np.sin(2 * np.pi * b / period), np.cos(2 * np.pi * b / period)])
    return np.linalg.norm(va - vb)


def test_brief_split_dates():
    train_start, test_start, as_of = split_bounds(date(2026, 10, 26))
    assert train_start == date(2026, 7, 26)
    assert test_start == date(2026, 10, 5)
    assert as_of == date(2026, 10, 26)


def test_boundary_day_is_test_only():
    frame = pd.DataFrame(
        {
            "loading_date": [
                date(2026, 7, 25),
                date(2026, 7, 26),
                date(2026, 10, 4),
                date(2026, 10, 5),
                date(2026, 10, 26),
                date(2026, 10, 27),
            ]
        }
    )
    train, test, future = split_by_loading_date(
        frame, date(2026, 10, 26), date(2026, 7, 26), date(2026, 10, 5)
    )
    assert set(pd.to_datetime(train["loading_date"]).dt.date) == {date(2026, 7, 26), date(2026, 10, 4)}
    assert set(pd.to_datetime(test["loading_date"]).dt.date) == {date(2026, 10, 5), date(2026, 10, 26)}
    assert set(pd.to_datetime(future["loading_date"]).dt.date) == {date(2026, 10, 27)}


def test_population_drops_auctions_complex_and_outliers():
    frame = pd.DataFrame(
        [
            {"is_fact": True, "complex": False, "outlier_mark": False, "price_rub": 10000, "distance": 100, "keep": 1},
            {"is_fact": False, "complex": False, "outlier_mark": False, "price_rub": 10000, "distance": 100, "keep": 0},
            {"is_fact": True, "complex": True, "outlier_mark": False, "price_rub": 10000, "distance": 100, "keep": 0},
            {"is_fact": True, "complex": False, "outlier_mark": True, "price_rub": 10000, "distance": 100, "keep": 0},
            {"is_fact": True, "complex": False, "outlier_mark": False, "price_rub": 0, "distance": 100, "keep": 0},
        ]
    )
    kept = model_population(frame)
    assert kept["keep"].tolist() == [1]


def test_features_do_not_include_the_target():
    assert set(FEATURES).isdisjoint(LEAKED_COLUMNS)
    prepared = prepare_features(
        pd.DataFrame(
            [
                {
                    "loading_date": date(2026, 12, 31),
                    "body_type": 56,
                    "body_group": "Тент",
                    "weight_category": "FTL",
                    "volume_category": "FTL",
                    "origin_city": "Казань",
                    "origin_region": None,
                    "dest_city": "Москва",
                    "dest_region": "г. Москва",
                    "distance": 800,
                    "total_weight": 20,
                    "total_volume": 80,
                    "origin_lat": 55.8,
                    "origin_lon": 49.1,
                    "dest_lat": 55.7,
                    "dest_lon": 37.6,
                }
            ]
        )
    )
    assert set(FEATURES).issubset(prepared.columns)
    assert prepared.loc[0, "origin_region"] == "unknown"
    assert prepared.loc[0, "body_type"] == "56"
    assert "price_rub" not in FEATURES


def test_december_sits_next_to_january():
    assert abs(_chord(12, 1, 12) - _chord(1, 2, 12)) < 1e-9
    assert _chord(12, 1, 12) < _chord(12, 6, 12)
    # Monday 0 and Sunday 6 are neighbours on a 7-day circle
    assert abs(_chord(0, 6, 7) - _chord(0, 1, 7)) < 1e-9
    frame = add_calendar_features(pd.DataFrame({"loading_date": [date(2026, 12, 31), date(2026, 1, 1)]}))
    dec = frame.iloc[0]
    jan = frame.iloc[1]
    dec_vec = np.array([dec["doy_sin"], dec["doy_cos"]])
    jan_vec = np.array([jan["doy_sin"], jan["doy_cos"]])
    assert np.linalg.norm(dec_vec - jan_vec) < 0.05


def test_future_quotes_do_not_keep_the_snapshot_price():
    scored = pd.DataFrame(
        [
            {
                "price_id": 7,
                "loading_date": date(2026, 11, 10),
                "loading_city_gcid": 1001,
                "unloading_city_gcid": 1004,
                "body_group": "Тент",
                "price_rub": 152000.0,
            }
        ]
    )
    frame = build_prediction_frame(
        scored,
        np.array([140000.0]),
        with_actual=False,
        model_name="catboost",
        scored_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert frame.loc[0, "predicted_price_rub"] == 140000.0
    assert pd.isna(frame.loc[0, "actual_price_rub"])
    assert pd.isna(frame.loc[0, "abs_error_rub"])
    assert pd.isna(frame.loc[0, "ape_pct"])


def test_metrics_on_a_tiny_pair():
    stats = regression_metrics([100.0, 200.0], [110.0, 160.0])
    assert stats["mae_rub"] == 25.0
    assert abs(stats["mape_pct"] - 15.0) < 1e-9
    assert abs(stats["r2"] - 0.66) < 1e-9


def test_sql_files_keep_the_body_map_and_skip_group_stats():
    core = (ROOT / "sql/dwh/01_core.sql").read_text(encoding="utf-8")
    assert "56, 57, 58, 59, 60, 61" in core
    assert "4, 46, 47, 48" in core
    assert "1, 15" in core
    statements = list(iter_statements(core))
    assert any("body_group_name" in statement for statement in statements)
    assert all(statement.strip().endswith(";") for statement in statements)

    dataset = (ROOT / "sql/ml/dataset.sql").read_text(encoding="utf-8")
    dataset_sql = "\n".join(
        line for line in dataset.splitlines() if not line.strip().startswith("--")
    )
    assert "price_group_stats" not in dataset_sql
    assert "price_with_vat" not in dataset_sql
    assert "min_km_price" not in dataset_sql

    mart = (ROOT / "sql/mart/route_card.sql").read_text(encoding="utf-8")
    assert "percentile_cont(0.25)" in mart
    assert "percentile_cont(0.50)" in mart
    assert "percentile_cont(0.75)" in mart
    assert "stddev_samp" in mart
    assert "price_type IN (3, 9)" in mart
    assert "interval '1 month'" in mart
    assert "interval '1 year'" in mart
    assert "outlier_mark" in mart
