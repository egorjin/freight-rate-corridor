import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.preprocessing import OrdinalEncoder
from sklearn.tree import DecisionTreeRegressor

from etl.db import ROOT, copy_rows, ensure_schema
from etl.settings import random_seed, split_bounds
from ml.features import (
    CAT_FEATURES,
    FEATURES,
    NUM_FEATURES,
    build_prediction_frame,
    model_population,
    prepare_features,
    split_by_loading_date,
)
from ml.metrics import regression_metrics

log = logging.getLogger(__name__)

PREDICTION_COLUMNS = (
    "price_id",
    "loading_date",
    "loading_city_gcid",
    "unloading_city_gcid",
    "body_group",
    "actual_price_rub",
    "predicted_price_rub",
    "abs_error_rub",
    "ape_pct",
    "model_name",
    "scored_at",
)


def read_dataset(conn, train_start, as_of):
    sql = (ROOT / "sql/ml/dataset.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql, {"train_start": train_start, "as_of": as_of})
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=columns)


def _fit_tree(train, test, seed):
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    train_cat = encoder.fit_transform(train[CAT_FEATURES])
    test_cat = encoder.transform(test[CAT_FEATURES])
    x_train = np.hstack([train[NUM_FEATURES].to_numpy(dtype=float), train_cat])
    x_test = np.hstack([test[NUM_FEATURES].to_numpy(dtype=float), test_cat])
    tree = DecisionTreeRegressor(
        max_depth=8,
        min_samples_leaf=40,
        random_state=seed,
    )
    tree.fit(x_train, train["price_rub"].to_numpy(dtype=float))
    return np.maximum(tree.predict(x_test), 0.0)


def _fit_catboost(train, test, future, seed):
    model = CatBoostRegressor(
        iterations=300,
        depth=6,
        learning_rate=0.1,
        loss_function="RMSE",
        random_seed=seed,
        thread_count=4,
        allow_writing_files=False,
        verbose=50,
    )
    model.fit(
        Pool(
            train[FEATURES],
            label=train["price_rub"].astype(float),
            cat_features=CAT_FEATURES,
        )
    )
    test_pred = model.predict(Pool(test[FEATURES], cat_features=CAT_FEATURES))
    future_pred = None
    if len(future):
        future_pred = model.predict(Pool(future[FEATURES], cat_features=CAT_FEATURES))
    return model, np.maximum(test_pred, 0.0), None if future_pred is None else np.maximum(future_pred, 0.0)


def _log_importance(model):
    scores = model.get_feature_importance()
    order = np.argsort(scores)[::-1][:8]
    for idx in order:
        log.info("feature %-16s %6.2f", FEATURES[idx], scores[idx])


def _store_metrics(cur, name, train_rows, test_rows, metrics, trained_at):
    cur.execute(
        """
        insert into mart.ml_run_metrics (
            model_name, train_rows, test_rows, r2, mape_pct, rmse_rub, mae_rub, trained_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (model_name) do update set
            train_rows = excluded.train_rows,
            test_rows = excluded.test_rows,
            r2 = excluded.r2,
            mape_pct = excluded.mape_pct,
            rmse_rub = excluded.rmse_rub,
            mae_rub = excluded.mae_rub,
            trained_at = excluded.trained_at
        """,
        (
            name,
            train_rows,
            test_rows,
            metrics["r2"],
            metrics["mape_pct"],
            metrics["rmse_rub"],
            metrics["mae_rub"],
            trained_at,
        ),
    )


def train_and_score(conn):
    ensure_schema(conn)
    train_start, test_start, as_of = split_bounds()
    raw = read_dataset(conn, train_start, as_of)
    log.info("model extract %s rows", len(raw))
    population = prepare_features(model_population(raw))
    train, test, future = split_by_loading_date(population, as_of, train_start, test_start)
    log.info(
        "split train=%s [%s, %s) test=%s [%s, %s] future=%s",
        len(train),
        train_start,
        test_start,
        len(test),
        test_start,
        as_of,
        len(future),
    )
    if train.empty or test.empty:
        raise SystemExit("train or test split is empty; core is probably not loaded for that window")

    seed = random_seed()
    tree_pred = _fit_tree(train, test, seed)
    tree_metrics = regression_metrics(test["price_rub"], tree_pred)
    log.info(
        "decision_tree  r2=%.4f mape=%.2f%% rmse=%.0f mae=%.0f",
        tree_metrics["r2"],
        tree_metrics["mape_pct"],
        tree_metrics["rmse_rub"],
        tree_metrics["mae_rub"],
    )

    model, test_pred, future_pred = _fit_catboost(train, test, future, seed)
    cat_metrics = regression_metrics(test["price_rub"], test_pred)
    log.info(
        "catboost       r2=%.4f mape=%.2f%% rmse=%.0f mae=%.0f",
        cat_metrics["r2"],
        cat_metrics["mape_pct"],
        cat_metrics["rmse_rub"],
        cat_metrics["mae_rub"],
    )
    _log_importance(model)

    scored_at = datetime.now(timezone.utc)
    frames = [
        build_prediction_frame(test, test_pred, True, "catboost", scored_at),
    ]
    if future_pred is not None:
        frames.append(build_prediction_frame(future, future_pred, False, "catboost", scored_at))
    predictions = pd.concat(frames, ignore_index=True)

    artifact = ROOT / "ml" / "artifacts"
    artifact.mkdir(parents=True, exist_ok=True)
    model.save_model(str(artifact / "tariff.cbm"))
    report = {
        "as_of": as_of.isoformat(),
        "train_start": train_start.isoformat(),
        "test_start": test_start.isoformat(),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "future_rows": int(len(future)),
        "decision_tree": tree_metrics,
        "catboost": cat_metrics,
    }
    (artifact / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    with conn.cursor() as cur:
        cur.execute("truncate mart.ml_price_predictions")
        copy_rows(cur, "mart.ml_price_predictions", PREDICTION_COLUMNS, predictions)
        _store_metrics(cur, "decision_tree", len(train), len(test), tree_metrics, scored_at)
        _store_metrics(cur, "catboost", len(train), len(test), cat_metrics, scored_at)
        cur.execute("analyze mart.ml_price_predictions")
    log.info("wrote %s predictions", len(predictions))
    return report
