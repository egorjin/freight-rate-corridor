#!/bin/bash
# Runs once, on an empty data volume. schema + synthetic snapshot + a marker
# the pipeline waits on. pg_isready goes green before this script finishes.
set -euo pipefail

echo "loading operational schema"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /sql/schema.sql

echo "generating ${N_PRICES:-300000} synthetic prices"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v n_prices="${N_PRICES:-300000}" \
  -f /sql/synthetic.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE TABLE public.source_ready (
    loaded_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.source_ready DEFAULT VALUES;
SQL

echo "source snapshot is ready"
