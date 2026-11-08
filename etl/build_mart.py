import logging

from etl.db import ROOT, ensure_schema

log = logging.getLogger(__name__)


def build_route_card(conn, as_of):
    ensure_schema(conn)
    sql = (ROOT / "sql/mart/route_card.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute("truncate mart.route_card")
        cur.execute(sql, {"as_of": as_of})
        cur.execute("analyze mart.route_card")
        cur.execute("select count(*) from mart.route_card")
        n_rows = cur.fetchone()[0]
        cur.execute(
            """
            select reliability_level, count(*)
            from mart.route_card
            group by 1
            order by 1
            """
        )
        levels = dict(cur.fetchall())
        cur.execute("select min(price_month), max(price_month) from mart.route_card")
        span = cur.fetchone()
    log.info("route card rows=%s months=%s..%s reliability=%s", n_rows, span[0], span[1], levels)
    return n_rows
