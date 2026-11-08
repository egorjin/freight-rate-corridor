import argparse
import logging
import os
import sys
from datetime import date

from etl.build_mart import build_route_card
from etl.db import connect, wait_for_source
from etl.load_core import load_core
from etl.settings import as_of_date
from ml.train_score import train_and_score

log = logging.getLogger("pipeline")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Clean deals, rebuild the route card, score tariffs."
    )
    parser.add_argument("--start", default=os.environ.get("ETL_START_DATE", "2019-01-01"))
    parser.add_argument("--end", default=os.environ.get("ETL_END_DATE", "2027-12-31"))
    parser.add_argument("--only", choices=("all", "etl", "mart", "ml"), default="all")
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="don't wait for public.source_ready (local database you loaded yourself)",
    )
    return parser.parse_args(argv)


def _stage(fn):
    with connect() as conn:
        with conn.transaction():
            return fn(conn)


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    args = parse_args(argv)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        raise SystemExit("--start is after --end")

    if not args.skip_wait:
        wait_for_source()

    as_of = as_of_date()
    if args.only in ("all", "etl"):
        log.info("etl window %s .. %s", start, end)
        _stage(lambda conn: load_core(conn, start, end))
    if args.only in ("all", "mart"):
        _stage(lambda conn: build_route_card(conn, as_of))
    if args.only in ("all", "ml"):
        _stage(lambda conn: train_and_score(conn))
    log.info("done")


if __name__ == "__main__":
    main()
