"""Read-only page over the route card and the batch forecast.

Vercel loads the FastAPI object named app. The heavy training libraries stay
out of this deploy; web/requirements.txt is what the install command uses.
"""

import os
from html import escape

import psycopg
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Freight rate corridor")

BODY_GROUPS = ("Тент", "Рефрижератор", "Изотерм", "Борт", "Прочие", "Не указан")
WEIGHTS = ("FTL", "G20T", "10T", "5T", "L5T", "OTH")


def connect():
    # Supabase's transaction pooler rejects prepared statements. Leaving them
    # off also works on a normal session connection.
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", ""),
        user=os.environ.get("POSTGRES_USER", ""),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        sslmode=os.environ.get("POSTGRES_SSLMODE", "require"),
        connect_timeout=10,
        prepare_threshold=None,
    )


def money(value):
    if value is None:
        return "—"
    return f"{round(float(value)):,.0f}".replace(",", " ")


def num(value, digits=1):
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def option(value, selected):
    mark = " selected" if value == selected else ""
    return f'<option value="{escape(value)}"{mark}>{escape(value)}</option>'


def page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0; font: 16px/1.45 "Segoe UI", sans-serif; color: #1c1917;
      background: #f6f3ee;
    }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ font-size: 28px; margin: 0 0 4px; }}
    h2 {{ font-size: 18px; margin: 32px 0 8px; }}
    p.lead {{ margin: 0 0 20px; color: #57534e; }}
    form {{
      display: flex; flex-wrap: wrap; gap: 10px; align-items: end;
      background: white; border: 1px solid #e7e5e4; padding: 12px;
    }}
    label {{ display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: #57534e; }}
    select {{ font: inherit; padding: 6px 8px; background: white; }}
    button {{ font: inherit; padding: 7px 14px; background: #1c1917; color: white; border: 0; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ text-align: right; padding: 8px 10px; border-bottom: 1px solid #e7e5e4; }}
    th:first-child, td:first-child, td.city {{ text-align: left; }}
    th {{ font-size: 12px; letter-spacing: 0.03em; color: #78716c; font-weight: 600; }}
    .cards {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .card {{ background: white; border: 1px solid #e7e5e4; padding: 12px 14px; min-width: 140px; }}
    .card b {{ display: block; font-size: 22px; }}
    .card span {{ color: #78716c; font-size: 13px; }}
    .HIGH {{ color: #166534; }}
    .MEDIUM {{ color: #a16207; }}
    .LOW_DATA {{ color: #78716c; }}
    .err {{ background: #fef2f2; border: 1px solid #fecaca; padding: 12px 14px; }}
  </style>
</head>
<body>
<main>
  <h1>Freight rate corridor</h1>
  <p class="lead">Closed deals in, monthly market range and a batch forecast out. Snapshot date 2026-10-26.</p>
  {body}
</main>
</body>
</html>"""


def error_page(message):
    html = page("Freight rate corridor", f'<p class="err">{escape(message)}</p>')
    return HTMLResponse(html, status_code=503)


@app.get("/", response_class=HTMLResponse)
def home(
    origin: int = Query(1001, ge=1, le=1_000_000),
    dest: int = Query(1003, ge=1, le=1_000_000),
    body: str = Query("Тент", max_length=40),
    weight: str = Query("FTL", max_length=8),
):
    if not os.environ.get("POSTGRES_DB") or not os.environ.get("POSTGRES_USER"):
        return error_page(
            "POSTGRES_DB and POSTGRES_USER are not set. Add the Supabase session "
            "connection values in the Vercel project settings, then redeploy."
        )
    if body not in BODY_GROUPS:
        body = "Тент"
    if weight not in WEIGHTS:
        weight = "FTL"

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                view = load_view(cur, origin, dest, body, weight)
    except psycopg.Error as exc:
        return error_page(f"Database query failed: {exc.__class__.__name__}")

    return HTMLResponse(page("Freight rate corridor", render(view)))


def load_view(cur, origin, dest, body, weight):
    cur.execute(
        """
        select gc_id, city_name
        from core.dim_cities
        order by city_name
        """
    )
    cities = cur.fetchall()

    cur.execute(
        """
        select
          (select count(*) from core.prices),
          (select count(*) from core.dq_quarantine_prices),
          (select count(*) from mart.route_card),
          (select count(*) from mart.ml_price_predictions)
        """
    )
    counts = cur.fetchone()

    cur.execute(
        """
        select model_name, train_rows, test_rows, r2, mape_pct, rmse_rub, mae_rub
        from mart.ml_run_metrics
        order by model_name
        """
    )
    metrics = cur.fetchall()

    cur.execute(
        """
        select price_month, trips_count, carriers_count, reliability_level,
               p25_trip, median_trip, p75_trip, median_km, mom_pct, yoy_pct,
               loading_city, unloading_city
        from mart.route_card
        where loading_city_gcid = %s
          and unloading_city_gcid = %s
          and body_group = %s
          and weight_category = %s
        order by price_month
        """,
        (origin, dest, body, weight),
    )
    lane = cur.fetchall()

    cur.execute(
        """
        select price_id, loading_date, body_group,
               actual_price_rub, predicted_price_rub, ape_pct
        from mart.ml_price_predictions
        where actual_price_rub is not null
        order by ape_pct desc
        limit 15
        """
    )
    misses = cur.fetchall()
    return {
        "cities": cities,
        "counts": counts,
        "metrics": metrics,
        "lane": lane,
        "misses": misses,
        "origin": origin,
        "dest": dest,
        "body": body,
        "weight": weight,
    }


def render(view):
    prices, quarantine, cells, predictions = view["counts"]
    origin_name, dest_name = "origin", "destination"
    if view["lane"]:
        origin_name = view["lane"][0][10]
        dest_name = view["lane"][0][11]

    city_options_from = []
    city_options_to = []
    for gc_id, name in view["cities"]:
        label = f"{name} ({gc_id})"
        city_options_from.append(
            f'<option value="{gc_id}"{" selected" if gc_id == view["origin"] else ""}>{escape(label)}</option>'
        )
        city_options_to.append(
            f'<option value="{gc_id}"{" selected" if gc_id == view["dest"] else ""}>{escape(label)}</option>'
        )

    lane_rows = []
    for row in view["lane"]:
        month, trips, carriers, level, p25, median, p75, per_km, mom, yoy = row[:10]
        lane_rows.append(
            "<tr>"
            f"<td>{escape(str(month))}</td>"
            f"<td>{trips}</td><td>{carriers}</td>"
            f'<td class="{escape(level)}">{escape(level)}</td>'
            f"<td>{money(p25)}</td><td>{money(median)}</td><td>{money(p75)}</td>"
            f"<td>{num(per_km, 2)}</td><td>{num(mom)}</td><td>{num(yoy)}</td>"
            "</tr>"
        )
    if not lane_rows:
        lane_rows.append('<tr><td colspan="10">No rows for this lane.</td></tr>')

    metric_rows = []
    for name, train_rows, test_rows, r2, mape, rmse, mae in view["metrics"]:
        metric_rows.append(
            "<tr>"
            f"<td>{escape(name)}</td>"
            f"<td>{train_rows} / {test_rows}</td>"
            f"<td>{num(r2, 4)}</td><td>{num(mape, 2)}%</td>"
            f"<td>{money(rmse)}</td><td>{money(mae)}</td>"
            "</tr>"
        )
    if not metric_rows:
        metric_rows.append('<tr><td colspan="6">No model run stored yet.</td></tr>')

    miss_rows = []
    for price_id, loading, group, actual, predicted, ape in view["misses"]:
        miss_rows.append(
            "<tr>"
            f"<td>{price_id}</td><td>{escape(str(loading))}</td>"
            f"<td>{escape(group or '')}</td>"
            f"<td>{money(actual)}</td><td>{money(predicted)}</td><td>{num(ape)}</td>"
            "</tr>"
        )

    return f"""
    <div class="cards">
      <div class="card"><b>{cells:,}</b><span>route-card cells</span></div>
      <div class="card"><b>{predictions:,}</b><span>forecasts</span></div>
      <div class="card"><b>{prices:,}</b><span>clean deals</span></div>
      <div class="card"><b>{quarantine:,}</b><span>quarantined</span></div>
    </div>

    <h2>Model</h2>
    <table>
      <thead><tr><th>Model</th><th>Train / test</th><th>R²</th><th>MAPE</th><th>RMSE, RUB</th><th>MAE, RUB</th></tr></thead>
      <tbody>{''.join(metric_rows)}</tbody>
    </table>

    <h2>Lane</h2>
    <form method="get">
      <label>From<select name="origin">{''.join(city_options_from)}</select></label>
      <label>To<select name="dest">{''.join(city_options_to)}</select></label>
      <label>Body<select name="body">{''.join(option(g, view["body"]) for g in BODY_GROUPS)}</select></label>
      <label>Weight<select name="weight">{''.join(option(w, view["weight"]) for w in WEIGHTS)}</select></label>
      <button type="submit">Show</button>
    </form>
    <p class="lead">{escape(origin_name)} → {escape(dest_name)}, {escape(view["body"])}, {escape(view["weight"])}. Prices are RUB per trip, without VAT.</p>
    <table>
      <thead>
        <tr>
          <th>Month</th><th>Trips</th><th>Carriers</th><th>Trust</th>
          <th>P25</th><th>Median</th><th>P75</th><th>RUB/km</th><th>MoM %</th><th>YoY %</th>
        </tr>
      </thead>
      <tbody>{''.join(lane_rows)}</tbody>
    </table>

    <h2>Largest forecast misses</h2>
    <table>
      <thead><tr><th>Deal</th><th>Loading</th><th>Body</th><th>Actual</th><th>Forecast</th><th>APE %</th></tr></thead>
      <tbody>{''.join(miss_rows)}</tbody>
    </table>
    """
