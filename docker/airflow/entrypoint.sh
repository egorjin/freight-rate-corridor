#!/bin/bash
set -eu

export PYTHONPATH="/opt/airflow/project${PYTHONPATH:+:$PYTHONPATH}"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$(python - <<'PY'
import os
from urllib.parse import quote_plus

user = quote_plus(os.environ["POSTGRES_USER"])
password = quote_plus(os.environ.get("POSTGRES_PASSWORD", ""))
host = os.environ.get("POSTGRES_HOST", "postgres")
print(f"postgresql+psycopg2://{user}:{password}@{host}:5432/airflow")
PY
)"

airflow db migrate

admin="${AIRFLOW_ADMIN_USER:-admin}"
if ! airflow users list 2>/dev/null | grep -q "$admin"; then
  airflow users create \
    --username "$admin" \
    --password "${AIRFLOW_ADMIN_PASSWORD:-admin}" \
    --firstname Rate \
    --lastname Desk \
    --role Admin \
    --email desk@localhost
fi

airflow webserver --port 8080 &
web_pid=$!
airflow scheduler &
sched_pid=$!

trap 'kill "$web_pid" "$sched_pid" 2>/dev/null || true' TERM INT
wait -n "$web_pid" "$sched_pid"
status=$?
kill "$web_pid" "$sched_pid" 2>/dev/null || true
exit "$status"
