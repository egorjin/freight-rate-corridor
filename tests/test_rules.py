from datetime import date

import pandas as pd

from etl.cities import dedup_cities, split_place
from etl.rules import assign_reasons, body_group, rejection_reason, volume_category, weight_category


def test_weight_bands_and_rounding():
    assert weight_category(30) == "G20T"
    assert weight_category(29.96) == "G20T"  # 30.0 after one decimal
    assert weight_category(29.94) == "FTL"
    assert weight_category(10) == "FTL"
    assert weight_category(9.96) == "FTL"
    assert weight_category(9.94) == "10T"
    assert weight_category(5) == "10T"
    assert weight_category(2.5) == "5T"
    assert weight_category(2.4) == "L5T"
    assert weight_category(0.5) == "L5T"
    assert weight_category(0.4) == "OTH"
    assert weight_category(0) == "OTH"


def test_volume_bands():
    assert volume_category(0) == "OTH"
    assert volume_category(0.1) == "FTL"
    assert volume_category(120) == "FTL"
    assert volume_category(120.1) == "OTH"
    assert volume_category(-1) == "OTH"


def test_body_groups():
    assert body_group(None) is None
    assert body_group(56) == "Тент"
    assert body_group(61) == "Тент"
    assert body_group(46) == "Рефрижератор"
    assert body_group(2) == "Изотерм"
    assert body_group(1) == "Борт"
    assert body_group(15) == "Борт"
    assert body_group(68) == "Прочие"


def test_place_name_split():
    assert split_place("Казань, Республика Татарстан") == ("Казань", "Республика Татарстан")
    assert split_place("Москва, г. Москва") == ("Москва", "г. Москва")
    assert split_place("Без региона") == ("Без региона", None)


def test_duplicate_gc_id_keeps_lowest_city_id():
    raw = pd.DataFrame(
        [
            {
                "id": 42,
                "gc_id": 1003,
                "name": "Казань",
                "full_name_local": "Казань г, Татарстан",
                "latitude": 55.8,
                "longitude": 49.1,
            },
            {
                "id": 3,
                "gc_id": 1003,
                "name": "Казань",
                "full_name_local": "Казань, Республика Татарстан",
                "latitude": 55.8,
                "longitude": 49.1,
            },
            {
                "id": 1,
                "gc_id": 1001,
                "name": "Москва",
                "full_name_local": "Москва, г. Москва",
                "latitude": 55.7,
                "longitude": 37.6,
            },
        ]
    )
    dim = dedup_cities(raw)
    assert len(dim) == 2
    kazan = dim.loc[dim["gc_id"] == 1003].iloc[0]
    assert kazan["city_id"] == 3
    assert kazan["city_name"] == "Казань"
    assert kazan["region_name"] == "Республика Татарстан"


def _row(**overrides):
    row = {
        "price": 84500.0,
        "currency_code": "643",
        "distance": 897.0,
        "total_weight": 20.0,
        "total_volume": 82.0,
        "loading_city_gcid": 1001,
        "unloading_city_gcid": 1003,
        "nearest_rate_date": date(2026, 9, 12),
        "loading_date": date(2026, 9, 15),
    }
    row.update(overrides)
    return row


CITIES = {1001, 1003, 1004}
RATES = {("840", date(2026, 10, 3)), ("978", date(2026, 10, 3))}


def test_reason_priority_and_kept_rows():
    assert rejection_reason(_row(), CITIES, RATES) is None
    # same city is not a DQ rule
    assert rejection_reason(_row(unloading_city_gcid=1001), CITIES, RATES) is None
    assert rejection_reason(_row(price=0), CITIES, RATES) == "non_positive_price"
    assert rejection_reason(_row(price=-10, distance=-1), CITIES, RATES) == "non_positive_price"
    assert rejection_reason(_row(price=1000), CITIES, RATES) == "rub_price_below_floor"
    assert rejection_reason(_row(price=1000.01), CITIES, RATES) is None
    assert rejection_reason(_row(distance=0), CITIES, RATES) == "bad_distance"
    assert rejection_reason(_row(total_weight=-0.1), CITIES, RATES) == "negative_weight"
    assert rejection_reason(_row(total_weight=0), CITIES, RATES) is None
    assert rejection_reason(_row(total_volume=-1), CITIES, RATES) == "negative_volume"
    assert rejection_reason(_row(loading_city_gcid=9999), CITIES, RATES) == "unknown_city"
    # floor wins over a missing city, so the stats stay stable
    assert rejection_reason(_row(price=500, loading_city_gcid=9999), CITIES, RATES) == "rub_price_below_floor"


def test_fx_uses_nearest_rate_date_only():
    usd = _row(price=2480, currency_code="840", nearest_rate_date=date(2026, 10, 3))
    assert rejection_reason(usd, CITIES, RATES) is None

    # a rate exists on loading_date, but nearest_rate_date is empty: still quarantine
    missing = _row(
        price=2480,
        currency_code="840",
        nearest_rate_date=None,
        loading_date=date(2026, 10, 3),
    )
    assert rejection_reason(missing, CITIES, RATES) == "missing_fx_rate"

    sunday = _row(price=2480, currency_code="840", nearest_rate_date=date(2026, 10, 4))
    assert rejection_reason(sunday, CITIES, RATES) == "missing_fx_rate"

    assert rejection_reason(_row(currency_code="999", price=50), CITIES, RATES) == "unknown_currency"


def test_vectorised_reasons_match_the_row_function():
    rows = [
        _row(),
        _row(price=0),
        _row(price=800),
        _row(distance=-5),
        _row(total_volume=-1),
        _row(loading_city_gcid=1, unloading_city_gcid=2),
        _row(price=2480, currency_code="840", nearest_rate_date=None),
        _row(price=2480, currency_code="840", nearest_rate_date=date(2026, 10, 3)),
        _row(unloading_city_gcid=1001),
    ]
    frame = pd.DataFrame(rows)
    got = assign_reasons(frame, CITIES, RATES)

    def norm(value):
        if value is None or value is pd.NA:
            return None
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass
        return value

    expected = [rejection_reason(row, CITIES, RATES) for row in rows]
    assert [norm(value) for value in got.tolist()] == expected
