"""Register the route-card dashboard. Safe to run again."""

import json
import os
import time

LANE_SQL = """
SELECT price_month,
       trips_count,
       carriers_count,
       reliability_level,
       round(p25_trip::numeric) AS p25_trip,
       round(median_trip::numeric) AS median_trip,
       round(p75_trip::numeric) AS p75_trip,
       round(mom_pct::numeric, 1) AS mom_pct
FROM mart.route_card
WHERE loading_city_gcid = 1001
  AND unloading_city_gcid = 1008
  AND body_group = 'Тент'
  AND weight_category = 'FTL'
ORDER BY price_month
"""

METRICS_SQL = """
SELECT model_name,
       train_rows,
       test_rows,
       round(r2::numeric, 4) AS r2,
       round(mape_pct::numeric, 2) AS mape_pct,
       round(rmse_rub::numeric) AS rmse_rub,
       round(mae_rub::numeric) AS mae_rub
FROM mart.ml_run_metrics
ORDER BY model_name
"""


def mart_uri():
    from superset_config import postgres_uri

    return postgres_uri(os.environ.get("POSTGRES_DB", "deals_bigdata"))


def wait_for_card():
    from sqlalchemy import create_engine, text

    deadline = time.time() + 3600
    last_error = None
    engine = create_engine(mart_uri())
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                ready = conn.execute(text("select to_regclass('mart.route_card')")).scalar()
                if ready is None:
                    raise RuntimeError("mart.route_card is not there yet")
                rows = conn.execute(text("select count(*) from mart.route_card")).scalar()
            if not rows:
                raise RuntimeError("mart.route_card is empty")
            return rows
        except Exception as exc:
            last_error = exc
            print(f"waiting for the route card: {exc.__class__.__name__}", flush=True)
            time.sleep(10)
    raise SystemExit(f"route card was not ready: {last_error}")


def upsert_database(db, Database, uri):
    database = db.session.query(Database).filter_by(database_name="deals_bigdata").one_or_none()
    if database is None:
        database = Database(database_name="deals_bigdata")
        db.session.add(database)
    database.set_sqlalchemy_uri(uri)
    database.expose_in_sqllab = True
    db.session.commit()
    return database


def upsert_dataset(db, SqlaTable, database, name, sql, admin):
    dataset = (
        db.session.query(SqlaTable)
        .filter_by(table_name=name, database_id=database.id)
        .one_or_none()
    )
    if dataset is None:
        dataset = SqlaTable(table_name=name, database=database, sql=sql)
        dataset.owners = [admin]
        db.session.add(dataset)
        db.session.commit()
    else:
        dataset.sql = sql
        db.session.commit()
    dataset.fetch_metadata()
    db.session.commit()
    return dataset


def upsert_chart(db, Slice, dataset, name, params, query):
    chart = db.session.query(Slice).filter_by(slice_name=name).one_or_none()
    payload = json.dumps(params)
    # The dashboard asks for the saved query. Params alone leave the chart blank.
    context = json.dumps(
        {
            "datasource": {"id": dataset.id, "type": "table"},
            "force": False,
            "queries": [query],
            "form_data": params,
            "result_format": "json",
            "result_type": "full",
        }
    )
    if chart is None:
        chart = Slice(
            slice_name=name,
            viz_type=params["viz_type"],
            datasource_type="table",
            datasource_id=dataset.id,
            params=payload,
            query_context=context,
        )
        db.session.add(chart)
    else:
        chart.viz_type = params["viz_type"]
        chart.datasource_type = "table"
        chart.datasource_id = dataset.id
        chart.params = payload
        chart.query_context = context
    db.session.commit()
    return chart


def dashboard_position(charts):
    layout = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "id": "HEADER_ID",
            "type": "HEADER",
            "meta": {"text": "Freight rate corridor"},
        },
    }
    row_ids = []
    for index, (chart, height) in enumerate(charts):
        row_id = f"ROW-{index}"
        chart_id = f"CHART-{index}"
        row_ids.append(row_id)
        layout[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [chart_id],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        layout[chart_id] = {
            "type": "CHART",
            "id": chart_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID", row_id],
            "meta": {
                "width": 12,
                "height": height,
                "chartId": chart.id,
                "sliceName": chart.slice_name,
            },
        }
    layout["GRID_ID"]["children"] = row_ids
    return layout


def main():
    rows = wait_for_card()
    print(f"route card rows={rows}", flush=True)

    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from flask_appbuilder.security.sqla.models import User
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        admin_name = os.environ.get("SUPERSET_ADMIN_USER", "admin")
        admin = db.session.query(User).filter_by(username=admin_name).one()
        database = upsert_database(db, Database, mart_uri())

        lane = upsert_dataset(
            db, SqlaTable, database, "moscow_rostov_tent_ftl", LANE_SQL, admin
        )
        metrics = upsert_dataset(
            db, SqlaTable, database, "ml_run_metrics", METRICS_SQL, admin
        )

        lane_columns = [
            "price_month",
            "trips_count",
            "carriers_count",
            "reliability_level",
            "p25_trip",
            "median_trip",
            "p75_trip",
            "mom_pct",
        ]
        median_metric = {
            "expressionType": "SIMPLE",
            "column": {"column_name": "median_trip"},
            "aggregate": "MAX",
            "label": "Median, RUB",
        }
        median = upsert_chart(
            db,
            Slice,
            lane,
            "Moscow to Rostov, tent FTL median",
            {
                "datasource": f"{lane.id}__table",
                "viz_type": "echarts_timeseries_line",
                "x_axis": "price_month",
                "time_grain_sqla": "P1M",
                "metrics": [median_metric],
                "groupby": [],
                "adhoc_filters": [],
                "row_limit": 500,
                "truncate_metric": True,
                "y_axis_format": ",.0f",
            },
            {
                "columns": [
                    {
                        "columnType": "BASE_AXIS",
                        "sqlExpression": "price_month",
                        "label": "price_month",
                        "expressionType": "SQL",
                        "timeGrain": "P1M",
                    }
                ],
                "metrics": [median_metric],
                "filters": [],
                "row_limit": 500,
                "orderby": [["price_month", True]],
                "extras": {"where": "", "having": ""},
                "series_columns": [],
            },
        )
        lane_table = upsert_chart(
            db,
            Slice,
            lane,
            "Moscow to Rostov, tent FTL",
            {
                "datasource": f"{lane.id}__table",
                "viz_type": "table",
                "query_mode": "raw",
                "all_columns": lane_columns,
                "order_by_cols": [],
                "row_limit": 500,
            },
            {
                "columns": lane_columns,
                "metrics": [],
                "filters": [],
                "row_limit": 500,
                "orderby": [["price_month", True]],
                "extras": {"where": "", "having": ""},
            },
        )
        metric_columns = [
            "model_name",
            "train_rows",
            "test_rows",
            "r2",
            "mape_pct",
            "rmse_rub",
            "mae_rub",
        ]
        metric_table = upsert_chart(
            db,
            Slice,
            metrics,
            "Model metrics",
            {
                "datasource": f"{metrics.id}__table",
                "viz_type": "table",
                "query_mode": "raw",
                "all_columns": metric_columns,
                "order_by_cols": [],
                "row_limit": 10,
            },
            {
                "columns": metric_columns,
                "metrics": [],
                "filters": [],
                "row_limit": 10,
                "orderby": [["model_name", True]],
                "extras": {"where": "", "having": ""},
            },
        )

        charts = [(metric_table, 20), (median, 50), (lane_table, 50)]
        board = db.session.query(Dashboard).filter_by(slug="route-card").one_or_none()
        if board is None:
            board = Dashboard(
                dashboard_title="Freight rate corridor",
                slug="route-card",
                published=True,
            )
            db.session.add(board)
        board.published = True
        board.owners = [admin]
        board.slices = [chart for chart, _height in charts]
        board.position_json = json.dumps(dashboard_position(charts))
        db.session.commit()
        print(f"dashboard id={board.id} slug=route-card", flush=True)


if __name__ == "__main__":
    main()
