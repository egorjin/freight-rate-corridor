import numpy as np
import pandas as pd

# Cats stay strings. CatBoost gets them by name; the tree baseline encodes
# them with an OrdinalEncoder fitted on train only.
CAT_FEATURES = [
    "origin_city",
    "origin_region",
    "dest_city",
    "dest_region",
    "body_group",
    "body_type",
    "weight_category",
    "volume_category",
]

NUM_FEATURES = [
    "distance",
    "total_weight",
    "total_volume",
    "origin_lat",
    "origin_lon",
    "dest_lat",
    "dest_lon",
    "year",
    "month",
    "dow",
    "doy",
    "month_sin",
    "month_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
]

FEATURES = NUM_FEATURES + CAT_FEATURES

# Anything derived from the tariff, or from a stat that already includes it.
LEAKED_COLUMNS = {
    "price",
    "price_rub",
    "price_with_vat",
    "price_km",
    "price_per_km",
    "price_per_ton",
    "outlier_mark",
    "price_group_id",
    "avg_price",
    "min_km_price",
    "max_km_price",
    "carrier_cost",
    "customer_cost",
    "profit",
}


def add_calendar_features(df):
    out = df.copy()
    loading = pd.to_datetime(out["loading_date"])
    out["year"] = loading.dt.year.astype(int)
    out["month"] = loading.dt.month.astype(int)
    out["dow"] = loading.dt.dayofweek.astype(int)  # Monday = 0
    out["doy"] = loading.dt.dayofyear.astype(int)
    out["month_sin"] = np.sin(2 * np.pi * out["month"] / 12.0)
    out["month_cos"] = np.cos(2 * np.pi * out["month"] / 12.0)
    out["dow_sin"] = np.sin(2 * np.pi * out["dow"] / 7.0)
    out["dow_cos"] = np.cos(2 * np.pi * out["dow"] / 7.0)
    out["doy_sin"] = np.sin(2 * np.pi * out["doy"] / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * out["doy"] / 365.25)
    return out


def _body_type_label(value):
    try:
        if value is None or pd.isna(value):
            return "unknown"
    except TypeError:
        return "unknown"
    return str(int(value))


def prepare_features(df):
    out = add_calendar_features(df)
    for col in (
        "distance",
        "total_weight",
        "total_volume",
        "origin_lat",
        "origin_lon",
        "dest_lat",
        "dest_lon",
    ):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["body_type"] = out["body_type"].map(_body_type_label)
    for col in CAT_FEATURES:
        if col == "body_type":
            continue
        out[col] = out[col].fillna("unknown").astype(str)
    return out


def model_population(df):
    """Facts, direct trips, positive rub and km, source outlier flag off.

    The flag is a filter. It is not a column the model gets to split on.
    """
    mask = (
        df["is_fact"].astype(bool)
        & ~df["complex"].astype(bool)
        & ~df["outlier_mark"].astype(bool)
        & (df["price_rub"] > 0)
        & (df["distance"] > 0)
    )
    return df.loc[mask].copy()


def split_by_loading_date(df, as_of, train_start, test_start):
    """2026-10-05 belongs to test only. Nothing is shuffled."""
    loading = pd.to_datetime(df["loading_date"]).dt.date
    train = df.loc[(loading >= train_start) & (loading < test_start)].copy()
    test = df.loc[(loading >= test_start) & (loading <= as_of)].copy()
    future = df.loc[loading > as_of].copy()
    return train, test, future


def build_prediction_frame(scored, predicted, with_actual, model_name, scored_at):
    predicted = np.maximum(np.asarray(predicted, dtype=float), 0.0)
    frame = pd.DataFrame(
        {
            "price_id": scored["price_id"].to_numpy(),
            "loading_date": pd.to_datetime(scored["loading_date"]).dt.date.to_numpy(),
            "loading_city_gcid": scored["loading_city_gcid"].to_numpy(),
            "unloading_city_gcid": scored["unloading_city_gcid"].to_numpy(),
            "body_group": scored["body_group"].to_numpy(),
            "predicted_price_rub": predicted,
            "model_name": model_name,
            "scored_at": scored_at,
        }
    )
    if with_actual:
        actual = scored["price_rub"].to_numpy(dtype=float)
        frame["actual_price_rub"] = actual
        frame["abs_error_rub"] = np.abs(actual - predicted)
        frame["ape_pct"] = np.abs(actual - predicted) / actual * 100.0
    else:
        # Planned loads still have a price in the snapshot. The comparison
        # columns stay empty: that price is not a realised trip.
        frame["actual_price_rub"] = np.nan
        frame["abs_error_rub"] = np.nan
        frame["ape_pct"] = np.nan
    return frame
