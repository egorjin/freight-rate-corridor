import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from etl.settings import pg_kwargs

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def connect():
    return psycopg.connect(**pg_kwargs())


def wait_for_source(timeout_sec=1800):
    """Postgres answers before init has finished loading prices. Wait for the marker."""
    deadline = time.time() + timeout_sec
    last_error = None
    while time.time() < deadline:
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select to_regclass('public.source_ready')")
                    marker = cur.fetchone()[0]
                    if marker is None:
                        raise RuntimeError("source_ready is not there yet")
                    cur.execute("select count(*) from public.source_ready")
                    if cur.fetchone()[0] < 1:
                        raise RuntimeError("source_ready is empty")
                    cur.execute("select count(*) from public.prices")
                    n_prices = cur.fetchone()[0]
            log.info("source database is ready, prices=%s", n_prices)
            return n_prices
        except Exception as exc:  # connection refused while init is still running
            last_error = exc
            log.info("waiting for source data: %s", exc.__class__.__name__)
            time.sleep(5)
    raise SystemExit(f"source database was not ready after {timeout_sec}s: {last_error}")


def iter_statements(script):
    """Split our DDL files. Dollar-quoted function bodies are kept intact."""
    buf = []
    in_dollar = False
    for line in script.splitlines():
        stripped = line.strip()
        if not in_dollar and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        if not in_dollar and stripped.endswith(";"):
            yield "\n".join(buf)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        yield tail


def execute_sql_file(conn, relative_path, params=None):
    path = ROOT / relative_path
    script = path.read_text(encoding="utf-8")
    statements = list(iter_statements(script))
    if not statements:
        raise RuntimeError(f"no statements in {relative_path}")
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement, params)
    log.info("applied %s (%s statements)", relative_path, len(statements))


def ensure_schema(conn):
    execute_sql_file(conn, "sql/dwh/01_core.sql")
    execute_sql_file(conn, "sql/dwh/02_mart.sql")


def _clean(value):
    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def copy_rows(cur, table, columns, frame):
    if frame.empty:
        log.info("nothing to copy into %s", table)
        return
    column_list = ", ".join(columns)
    sql = f"COPY {table} ({column_list}) FROM STDIN"
    records = frame.loc[:, list(columns)].itertuples(index=False, name=None)
    with cur.copy(sql) as copy:
        for record in records:
            copy.write_row(tuple(_clean(value) for value in record))
