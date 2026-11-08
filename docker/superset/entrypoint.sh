#!/bin/bash
set -eu

superset db upgrade

admin="${SUPERSET_ADMIN_USER:-admin}"
if ! superset fab list-users | grep -q "$admin"; then
  superset fab create-admin \
    --username "$admin" \
    --firstname Rate \
    --lastname Desk \
    --email desk@localhost \
    --password "${SUPERSET_ADMIN_PASSWORD:-admin}"
fi

superset init
python /app/bootstrap_dashboard.py
exec superset run --host 0.0.0.0 --port 8088
