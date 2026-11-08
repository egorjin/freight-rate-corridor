"""Copy mart.route_card into ClickHouse. The mart itself stays in Postgres."""

import base64
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

# Same columns, same order, as sql/dwh/02_mart.sql and sql/clickhouse/route_card.sql.
COLUMNS = (
    "price_month",
    "loading_city_gcid",
    "unloading_city_gcid",
    "loading_city",
    "unloading_city",
    "loading_region",
    "unloading_region",
    "body_group",
    "weight_category",
    "trips_count",
    "carriers_count",
    "p25_trip",
    "median_trip",
    "p75_trip",
    "avg_trip",
    "p25_km",
    "median_km",
    "p75_km",
    "cv_rate",
    "mom_pct",
    "yoy_pct",
    "max_price_date",
    "reliability_level",
    "as_of_date",
    "built_at",
)

GRAIN = (
    "price_month",
    "loading_city_gcid",
    "unloading_city_gcid",
    "body_group",
    "weight_category",
)


def _quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def _redact(text, password):
    if password:
        return text.replace(password, "***")
    return text


def insert_sql(host, port, dbname, user, password):
    selected = []
    for name in COLUMNS:
        if name == "built_at":
            selected.append("cast(built_at as DateTime64(6, 'UTC'))")
        else:
            selected.append(name)
    source = (
        "postgresql("
        f"{_quote(f'{host}:{port}')}, {_quote(dbname)}, {_quote('route_card')}, "
        f"{_quote(user)}, {_quote(password)}, {_quote('mart')}"
        ")"
    )
    return (
        f"INSERT INTO mart.route_card ({', '.join(COLUMNS)}) "
        f"SELECT {', '.join(selected)} FROM {source}"
    )


def _statements(script):
    buf = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            yield "\n".join(buf)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        yield tail


def _clickhouse(sql):
    host = os.environ.get("CLICKHOUSE_HOST", "clickhouse")
    port = os.environ.get("CLICKHOUSE_PORT", "8123")
    user = os.environ.get("CLICKHOUSE_USER", "default")
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    database = os.environ.get("CLICKHOUSE_DB", "mart")
    url = f"http://{host}:{port}/?database={urllib.parse.quote(database)}"
    request = urllib.request.Request(url, data=sql.encode("utf-8"), method="POST")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(_redact(body, password)) from exc


def _wait_for_card(timeout_sec=3600):
    from etl.db import connect

    deadline = time.time() + timeout_sec
    last_error = None
    while time.time() < deadline:
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select to_regclass('mart.route_card')")
                    if cur.fetchone()[0] is None:
                        raise RuntimeError("mart.route_card is not there yet")
                    cur.execute(
                        "select count(*), coalesce(sum(trips_count), 0) from mart.route_card"
                    )
                    count, trips = cur.fetchone()
            if count < 1:
                raise RuntimeError("mart.route_card is empty")
            return int(count), int(trips)
        except Exception as exc:
            last_error = exc
            log.info("waiting for the route card: %s", exc.__class__.__name__)
            time.sleep(10)
    raise SystemExit(f"route card was not ready after {timeout_sec}s: {last_error}")


def sync_route_card():
    rows, trips = _wait_for_card()
    log.info("postgres route card rows=%s trips=%s", rows, trips)

    ddl = (ROOT / "sql" / "clickhouse" / "route_card.sql").read_text(encoding="utf-8")
    for statement in _statements(ddl):
        _clickhouse(statement)

    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    # ClickHouse reaches the database on the compose network, not via the host port.
    if host in ("localhost", "127.0.0.1"):
        host = "postgres"
        port = 5432
    _clickhouse(
        insert_sql(
            host,
            port,
            os.environ["POSTGRES_DB"],
            os.environ["POSTGRES_USER"],
            os.environ.get("POSTGRES_PASSWORD", ""),
        )
    )
    _clickhouse("OPTIMIZE TABLE mart.route_card FINAL")

    copied = _clickhouse(
        "SELECT count(), sum(trips_count) FROM mart.route_card FINAL FORMAT TabSeparated"
    )
    copied_rows, copied_trips = (int(part) for part in copied.split())
    log.info("clickhouse route card rows=%s trips=%s", copied_rows, copied_trips)
    if (copied_rows, copied_trips) != (rows, trips):
        raise SystemExit(
            "clickhouse copy does not match postgres: "
            f"{copied_rows} rows / {copied_trips} trips against {rows} / {trips}"
        )
    return copied_rows


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sync_route_card()


if __name__ == "__main__":
    main()
