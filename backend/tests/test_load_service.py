from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.load_service import run_full_load
from app.models import DataSource


def test_full_load_extracts_to_st_and_merges_l0(tmp_path: Path):
    source_path = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{source_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO orders(id, name) VALUES (1, 'one'), (2, 'two')"))

    source = DataSource(name="fixture", db_type="sqlite", database=str(source_path), host="", username="")
    result = run_full_load(
        source,
        schema_name="main",
        table_name="orders",
        key_columns=["id"],
        batch_id="test-001",
        root=tmp_path / "lake",
    )

    assert result["source_count"] == 2
    assert result["staging_path"].endswith("/st/main/orders/batch-test-001.parquet")
    assert result["l0"]["row_count"] == 2


def test_full_load_rejects_empty_source(tmp_path: Path):
    source_path = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{source_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, name TEXT)"))

    source = DataSource(name="empty", db_type="sqlite", database=str(source_path), host="", username="")
    with pytest.raises(ValueError, match="empty"):
        run_full_load(
            source,
            schema_name="main",
            table_name="orders",
            key_columns=["id"],
            batch_id="test-empty",
            root=tmp_path / "lake",
        )
