import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="set RUN_DB_TESTS=1 and POSTGRES_* to hit a loaded database",
)


def test_reloading_a_window_does_not_double_rows():
    from datetime import date

    from etl.build_mart import build_route_card
    from etl.db import connect
    from etl.load_core import load_core
    from etl.settings import as_of_date

    start, end = date(2026, 9, 1), date(2026, 9, 30)

    def snapshot():
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select count(*)::int,
                           round(coalesce(sum(price_rub), 0)::numeric, 2)
                    from core.prices
                    where loading_date between %s and %s
                    """,
                    (start, end),
                )
                core = cur.fetchone()
                cur.execute(
                    """
                    select reason, count(*)
                    from core.dq_quarantine_prices
                    where loading_date between %s and %s
                    group by 1
                    order by 1
                    """,
                    (start, end),
                )
                quarantine = cur.fetchall()
                cur.execute(
                    """
                    select count(*)::int,
                           round(coalesce(sum(median_trip), 0)::numeric, 2)
                    from mart.route_card
                    """
                )
                mart = cur.fetchone()
        return core, quarantine, mart

    with connect() as conn:
        with conn.transaction():
            load_core(conn, start, end)
            build_route_card(conn, as_of_date())
    first = snapshot()

    with connect() as conn:
        with conn.transaction():
            load_core(conn, start, end)
            build_route_card(conn, as_of_date())
    second = snapshot()

    assert first == second
    assert first[0][0] > 0
