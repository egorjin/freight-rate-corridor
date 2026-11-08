"""Daily rebuild of the corridor.

The source extract is one fixed snapshot, so a run replaces the same window
instead of ingesting a new day. The DAG is paused until someone unpauses it.
"""

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def run_etl():
    import os
    from datetime import date

    from etl.db import connect
    from etl.load_core import load_core

    start = date.fromisoformat(os.environ.get("ETL_START_DATE", "2019-01-01"))
    end = date.fromisoformat(os.environ.get("ETL_END_DATE", "2027-12-31"))
    with connect() as conn:
        with conn.transaction():
            load_core(conn, start, end)


def run_mart():
    from etl.build_mart import build_route_card
    from etl.db import connect
    from etl.settings import as_of_date

    with connect() as conn:
        with conn.transaction():
            build_route_card(conn, as_of_date())


def run_ml():
    from etl.db import connect
    from ml.train_score import train_and_score

    with connect() as conn:
        with conn.transaction():
            train_and_score(conn)


def run_clickhouse():
    from etl.sync_clickhouse import sync_route_card

    sync_route_card()


with DAG(
    dag_id="freight_rate_corridor",
    start_date=datetime(2026, 10, 26),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "corridor", "retries": 0},
    tags=["corridor"],
    description="Rebuild core, the route card, the tariff model, and the ClickHouse copy.",
) as dag:
    etl = PythonOperator(task_id="etl", python_callable=run_etl)
    mart = PythonOperator(task_id="route_card", python_callable=run_mart)
    ml = PythonOperator(task_id="score", python_callable=run_ml)
    ch = PythonOperator(task_id="clickhouse", python_callable=run_clickhouse)
    etl >> mart >> [ml, ch]
