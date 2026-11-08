FROM apache/airflow:2.10.4-python3.11

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements-pipeline.txt
COPY docker/airflow/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER airflow
# The 2.10.4 constraint file pins pandas 2.1.4. The pipeline is pinned to 2.2.3,
# so this install does not use that file.
RUN pip install --no-cache-dir -r /tmp/requirements-pipeline.txt

ENTRYPOINT ["/entrypoint.sh"]
