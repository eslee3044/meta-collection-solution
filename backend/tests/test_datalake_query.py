from pathlib import Path

import duckdb
import pytest

from app.datalake_query import DatalakeTableNotFound, list_l0_tables, preview_l0_table


def make_l0(root: Path) -> Path:
    db = root / "l0" / "l0.duckdb"
    db.parent.mkdir(parents=True)
    con = duckdb.connect(str(db))
    con.execute('CREATE SCHEMA "sales"')
    con.execute('CREATE TABLE "sales"."orders" (id INTEGER, status VARCHAR)')
    con.execute("INSERT INTO \"sales\".\"orders\" VALUES (1, 'paid'), (2, 'pending')")
    con.close()
    return db


def test_list_l0_tables_returns_metadata(tmp_path: Path):
    make_l0(tmp_path)

    assert list_l0_tables(tmp_path) == [
        {"schema_name": "sales", "table_name": "orders", "row_count": 2}
    ]


def test_preview_l0_table_is_limited_and_json_ready(tmp_path: Path):
    make_l0(tmp_path)

    result = preview_l0_table(tmp_path, "sales", "orders", limit=1)

    assert result["schema_name"] == "sales"
    assert result["table_name"] == "orders"
    assert result["columns"] == ["id", "status"]
    assert result["rows"] == [{"id": 1, "status": "paid"}]
    assert result["limit"] == 1


def test_preview_rejects_missing_table_and_unsafe_identifier(tmp_path: Path):
    make_l0(tmp_path)

    with pytest.raises(DatalakeTableNotFound):
        preview_l0_table(tmp_path, "sales", "missing", limit=10)
    with pytest.raises(ValueError):
        preview_l0_table(tmp_path, "sales;DROP", "orders", limit=10)
