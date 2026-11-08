FROM apache/superset:4.1.2

USER root
RUN pip install --no-cache-dir psycopg2-binary \
    && mkdir -p /app/pythonpath
COPY docker/superset/superset_config.py /app/pythonpath/superset_config.py
COPY docker/superset/bootstrap.py /app/bootstrap_dashboard.py
COPY docker/superset/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER superset
ENTRYPOINT ["/app/entrypoint.sh"]
