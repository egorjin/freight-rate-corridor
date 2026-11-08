import os
from datetime import date, timedelta


def _need(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"environment variable {name} is not set (see .env.example)")
    return value


def pg_kwargs():
    return {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "dbname": _need("POSTGRES_DB"),
        "user": _need("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
    }


def as_of_date():
    # The snapshot date from the brief. Not the day the container happens to start.
    raw = os.environ.get("AS_OF_DATE", "2026-10-26")
    return date.fromisoformat(raw)


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # 2026-10-26 minus 3 months is 2026-07-26, so the day does not need clamping
    # for the snapshot we actually use. Still clamp so a short month does not crash.
    month_lengths = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(day.day, month_lengths[month - 1]))


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def split_bounds(as_of=None):
    """Train is [as_of - 3 months, as_of - 21 days). Test is [that day, as_of]."""
    as_of = as_of or as_of_date()
    train_start = add_months(as_of, -3)
    test_start = as_of - timedelta(days=21)
    return train_start, test_start, as_of


def random_seed():
    return int(os.environ.get("RANDOM_SEED", "42"))
