import ast
import re
from pathlib import Path

from etl.sync_clickhouse import COLUMNS, GRAIN, insert_sql

ROOT = Path(__file__).resolve().parents[1]


def _route_card_columns():
    text = (ROOT / "sql" / "dwh" / "02_mart.sql").read_text(encoding="utf-8")
    body = text.split("CREATE TABLE IF NOT EXISTS mart.route_card", 1)[1]
    body = body.split("PRIMARY KEY", 1)[0]
    return re.findall(r"^\s{4}([a-z0-9_]+)\s+", body, re.M)


def test_clickhouse_copy_uses_the_postgres_grain():
    ddl = (ROOT / "sql" / "clickhouse" / "route_card.sql").read_text(encoding="utf-8")
    mart = (ROOT / "sql" / "dwh" / "02_mart.sql").read_text(encoding="utf-8")
    assert "ReplacingMergeTree(built_at)" in ddl
    assert _route_card_columns() == list(COLUMNS)
    grain = ", ".join(GRAIN)
    for text in (ddl, mart):
        folded = re.sub(r"\s+", " ", text)
        assert grain in folded
        for column in COLUMNS:
            assert column in text


def test_insert_quotes_a_password_and_names_every_column():
    sql = insert_sql("postgres", 5432, "deals_bigdata", "postgres", "p'wd")
    assert "postgresql(" in sql
    assert "p''wd" in sql
    assert "p'wd" not in sql.replace("p''wd", "")
    for column in COLUMNS:
        assert column in sql


def test_dag_file_parses_and_names_the_four_tasks():
    path = ROOT / "dags" / "freight_corridor.py"
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    for task_id in ("etl", "route_card", "score", "clickhouse"):
        assert f'task_id="{task_id}"' in text
    assert "etl >> mart >> [ml, ch]" in text
    # Heavy imports stay inside the task callables so the scheduler can parse the file.
    module = ast.parse(text)
    imported = []
    for node in module.body:
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "etl" not in imported
    assert "pandas" not in imported
    assert "catboost" not in imported
