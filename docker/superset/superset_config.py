import os
from urllib.parse import quote_plus


def postgres_uri(database):
    user = quote_plus(os.environ["POSTGRES_USER"])
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", ""))
    host = os.environ.get("POSTGRES_HOST", "postgres")
    return f"postgresql+psycopg2://{user}:{password}@{host}:5432/{database}"


SQLALCHEMY_DATABASE_URI = postgres_uri("superset")
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "local-corridor-superset-secret")

# The demo is plain HTTP on localhost. Talisman's HTTPS headers get in the way.
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = True
SUPERSET_WEBSERVER_PORT = 8088
