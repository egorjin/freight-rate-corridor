import logging

import numpy as np
import pandas as pd

from etl.cities import dedup_cities
from etl.db import copy_rows, ensure_schema
from etl.rules import (
    FX_CODES,
    RUB,
    _as_date,
    assign_reasons,
    volume_category,
    weight_category,
)

log = logging.getLogger(__name__)

PRICE_SQL = """
    select
        id as price_id,
        created_at,
        loading_date,
        end_loading_date,
        loading_city_gcid,
        unloading_city_gcid,
        distance,
        total_weight,
        total_volume,
        body_type,
        price,
        currency_code,
        complex,
        price_type,
        is_fact,
        organization_id,
        subscriber_id,
        nearest_rate_date,
        outlier_mark,
        weight_category,
        volume_category
    from public.prices
    where loading_date between %s and %s
"""

# price_group_id is intentionally not selected. The night job builds it from
# the raw price of the same deals, so it must not leak into core or the model.

CORE_COLUMNS = (
    "price_id",
    "loading_date",
    "end_loading_date",
    "loading_city_gcid",
    "unloading_city_gcid",
    "distance",
    "total_weight",
    "total_volume",
    "body_type",
    "price",
    "currency_code",
    "fx_rate",
    "fx_rate_date",
    "price_rub",
    "complex",
    "price_type",
    "is_fact",
    "organization_id",
    "subscriber_id",
    "outlier_mark",
    "weight_category",
    "volume_category",
    "created_at",
)

QUARANTINE_COLUMNS = (
    "price_id",
    "loading_date",
    "reason",
    "price",
    "currency_code",
    "distance",
    "total_weight",
    "total_volume",
    "loading_city_gcid",
    "unloading_city_gcid",
    "nearest_rate_date",
)


def _as_int(value):
    # A null in an otherwise integer column makes pandas store 56 as 56.0.
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    return int(value)


def _int_columns(frame, columns):
    # Assigning ints back into a float64 column (nulls promoted the dtype)
    # turns 56 into 56.0 again, and COPY rejects that. Drop the column first.
    out = frame.copy()
    for column in columns:
        if column not in out.columns:
            continue
        values = [_as_int(value) for value in out[column].tolist()]
        out = out.drop(columns=[column])
        out[column] = pd.Series(values, index=out.index, dtype=object)
    return out


def _read_frame(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=columns)


def _blank(series):
    text = series.astype("string").str.strip()
    return series.isna() | text.isna() | (text == "") | (text == "<NA>")


def fill_categories(df):
    out = df.copy()
    missing_weight = _blank(out["weight_category"])
    missing_volume = _blank(out["volume_category"])
    if missing_weight.any():
        out.loc[missing_weight, "weight_category"] = (
            out.loc[missing_weight, "total_weight"].map(weight_category)
        )
    if missing_volume.any():
        out.loc[missing_volume, "volume_category"] = (
            out.loc[missing_volume, "total_volume"].map(volume_category)
        )
    return out


def load_rates(conn):
    frame = _read_frame(
        conn,
        """
        select num_code, setting_date, value
        from public.exchange_rates
        where num_code = any(%s)
        """,
        (list(FX_CODES),),
    )
    keys = set()
    values = {}
    for code, setting_date, value in frame.itertuples(index=False):
        day = _as_date(setting_date)
        keys.add((code, day))
        values[(code, day)] = float(value)
    return keys, values


def load_city_ids(conn):
    frame = _read_frame(conn, "select distinct gc_id from public.cities", ())
    return set(int(v) for v in frame["gc_id"].tolist())


def attach_rub(df, rate_values):
    out = df.copy()
    fx_rate = np.ones(len(out), dtype="float64")
    price_rub = pd.to_numeric(out["price"], errors="coerce").to_numpy(dtype="float64").copy()
    fx_dates = []
    for i, (code, raw_date, price) in enumerate(
        zip(out["currency_code"].tolist(), out["nearest_rate_date"].tolist(), price_rub)
    ):
        if code == RUB or code not in FX_CODES:
            fx_dates.append(None)
            continue
        day = _as_date(raw_date)
        rate = rate_values.get((code, day))
        if rate is None:
            fx_rate[i] = np.nan
            price_rub[i] = np.nan
            fx_dates.append(None)
            continue
        fx_rate[i] = rate
        price_rub[i] = float(price) * rate
        fx_dates.append(day)
    out["fx_rate"] = fx_rate
    out["fx_rate_date"] = fx_dates
    out["price_rub"] = price_rub
    return out


def refresh_dim_cities(conn):
    raw = _read_frame(
        conn,
        """
        select id, gc_id, name, full_name_local, latitude, longitude
        from public.cities
        """,
        (),
    )
    dim = dedup_cities(raw)
    with conn.cursor() as cur:
        cur.execute("truncate core.dim_cities")
        copy_rows(
            cur,
            "core.dim_cities",
            (
                "gc_id",
                "city_id",
                "city_name",
                "region_name",
                "full_name_local",
                "latitude",
                "longitude",
            ),
            dim,
        )
    log.info("dim cities %s rows (source had %s)", len(dim), len(raw))


def load_core(conn, start, end):
    ensure_schema(conn)
    refresh_dim_cities(conn)

    raw = _read_frame(conn, PRICE_SQL, (start, end))
    log.info("read %s prices for loading_date %s .. %s", len(raw), start, end)
    if raw.empty:
        with conn.cursor() as cur:
            cur.execute(
                "delete from core.prices where loading_date between %s and %s",
                (start, end),
            )
            cur.execute(
                "delete from core.dq_quarantine_prices where loading_date between %s and %s",
                (start, end),
            )
        log.info("window is empty, cleared core and quarantine for it")
        return

    city_ids = load_city_ids(conn)
    rate_keys, rate_values = load_rates(conn)
    prepared = fill_categories(raw)
    prepared = attach_rub(prepared, rate_values)
    prepared["reason"] = assign_reasons(prepared, city_ids, rate_keys)
    # A row with no reason and no rub amount would vanish. Keep it in quarantine.
    lost = prepared["reason"].isna() & prepared["price_rub"].isna()
    prepared.loc[lost, "reason"] = "missing_fx_rate"

    rejected = prepared[prepared["reason"].notna()].copy()
    accepted = prepared[prepared["reason"].isna()].copy()
    accepted["weight_category"] = accepted["weight_category"].fillna("OTH")
    accepted["volume_category"] = accepted["volume_category"].fillna("OTH")

    int_cols = (
        "price_id",
        "loading_city_gcid",
        "unloading_city_gcid",
        "body_type",
        "price_type",
        "organization_id",
        "subscriber_id",
    )
    accepted = _int_columns(accepted, int_cols)
    rejected = _int_columns(rejected, int_cols)

    counts = rejected["reason"].value_counts().to_dict() if not rejected.empty else {}
    log.info("quarantine %s rows %s", len(rejected), counts)
    log.info("accepted %s rows", len(accepted))

    # Replace this loading_date window in one transaction (caller commits).
    # A repeated run deletes the same slice before copying it back.
    with conn.cursor() as cur:
        cur.execute(
            "delete from core.prices where loading_date between %s and %s",
            (start, end),
        )
        cur.execute(
            "delete from core.dq_quarantine_prices where loading_date between %s and %s",
            (start, end),
        )
        copy_rows(cur, "core.dq_quarantine_prices", QUARANTINE_COLUMNS, rejected)
        copy_rows(cur, "core.prices", CORE_COLUMNS, accepted)
        cur.execute("analyze core.prices")
        cur.execute("analyze core.dq_quarantine_prices")

    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*), coalesce(sum(price_rub), 0)
            from core.prices
            where loading_date between %s and %s
            """,
            (start, end),
        )
        n_core, rub_sum = cur.fetchone()
        cur.execute(
            """
            select count(*)
            from core.dq_quarantine_prices
            where loading_date between %s and %s
            """,
            (start, end),
        )
        n_bad = cur.fetchone()[0]
    log.info("core window rows=%s sum_price_rub=%.2f quarantine=%s", n_core, rub_sum, n_bad)
