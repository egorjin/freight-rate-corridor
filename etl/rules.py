from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

# 1C body ids collapsed to the groups procurement actually talks about.
# NULL stays NULL here; callers label that as "Не указан".
_BODY_GROUPS = (
    (frozenset((56, 57, 58, 59, 60, 61)), "Тент"),
    (frozenset((4, 46, 47, 48)), "Рефрижератор"),
    (frozenset((2,)), "Изотерм"),
    (frozenset((1, 15)), "Борт"),
)

RUB = "643"
FX_CODES = ("840", "978")
KNOWN_CURRENCIES = (RUB,) + FX_CODES

# First match wins. A zero price is reported as non_positive even when the
# distance is also broken, otherwise the quarantine stats get hard to read.
REASON_PRIORITY = (
    "non_positive_price",
    "rub_price_below_floor",
    "bad_distance",
    "negative_weight",
    "negative_volume",
    "unknown_city",
    "unknown_currency",
    "missing_fx_rate",
)


def round_tons(weight):
    # PostgreSQL round(numeric, 1) is half away from zero. Python round() is not.
    dec = Decimal(str(weight))
    return dec.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def weight_category(total_weight):
    if total_weight is None or total_weight != total_weight:
        return None
    tons = round_tons(total_weight)
    if tons >= 30:
        return "G20T"
    if tons >= 10:
        return "FTL"
    if tons >= 5:
        return "10T"
    if tons >= Decimal("2.5"):
        return "5T"
    if tons >= Decimal("0.5"):
        return "L5T"
    return "OTH"


def volume_category(total_volume):
    if total_volume is None or total_volume != total_volume:
        return None
    # 0 m3 is OTH, 120 is still FTL, anything above is OTH.
    if 0 < float(total_volume) <= 120:
        return "FTL"
    return "OTH"


def body_group(body_type_id):
    if body_type_id is None or body_type_id != body_type_id:
        return None
    code = int(body_type_id)
    for ids, name in _BODY_GROUPS:
        if code in ids:
            return name
    return "Прочие"


def _as_date(value):
    if value is None:
        return None
    try:
        if value != value:  # NaN / NaT
            return None
    except TypeError:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    return value


def rejection_reason(row, city_ids, rate_keys):
    """One primary DQ reason, or None when the row can enter core.

    loading_city_gcid == unloading_city_gcid is not a reason. The source job
    keeps that pair, and the brief says not to invent the rule.

    Foreign currency uses the rate on nearest_rate_date only. That column is
    filled from created_at upstream. We do not look up a rate by loading_date.
    """
    price = row["price"]
    if price is None or price != price or price <= 0:
        return "non_positive_price"

    currency = row["currency_code"]
    if currency == RUB and price <= 1000:
        return "rub_price_below_floor"

    distance = row["distance"]
    if distance is None or distance != distance or distance <= 0:
        return "bad_distance"

    weight = row["total_weight"]
    if weight is not None and weight == weight and weight < 0:
        return "negative_weight"

    volume = row["total_volume"]
    if volume is not None and volume == volume and volume < 0:
        return "negative_volume"

    if row["loading_city_gcid"] not in city_ids or row["unloading_city_gcid"] not in city_ids:
        return "unknown_city"

    if currency not in KNOWN_CURRENCIES:
        return "unknown_currency"

    if currency in FX_CODES:
        rate_date = _as_date(row["nearest_rate_date"])
        if rate_date is None or (currency, rate_date) not in rate_keys:
            return "missing_fx_rate"

    return None


def assign_reasons(df, city_ids, rate_keys):
    """Same priority as rejection_reason, vectorised for the batch."""
    import pandas as pd

    reason = pd.Series(pd.NA, index=df.index, dtype="object")

    def take(mask, code):
        nonlocal reason
        reason = reason.mask(mask.fillna(False) & reason.isna(), code)

    price = df["price"]
    take(price.isna() | (price <= 0), "non_positive_price")
    take((df["currency_code"] == RUB) & (price <= 1000), "rub_price_below_floor")

    distance = df["distance"]
    take(distance.isna() | (distance <= 0), "bad_distance")
    take(df["total_weight"].notna() & (df["total_weight"] < 0), "negative_weight")
    take(df["total_volume"].notna() & (df["total_volume"] < 0), "negative_volume")

    known_city = df["loading_city_gcid"].isin(city_ids) & df["unloading_city_gcid"].isin(city_ids)
    take(~known_city, "unknown_city")
    take(~df["currency_code"].isin(KNOWN_CURRENCIES), "unknown_currency")

    dates = [_as_date(v) for v in df["nearest_rate_date"].tolist()]
    codes = df["currency_code"].tolist()
    missing_fx = [
        code in FX_CODES and (dt is None or (code, dt) not in rate_keys)
        for code, dt in zip(codes, dates)
    ]
    take(pd.Series(missing_fx, index=df.index), "missing_fx_rate")
    return reason
