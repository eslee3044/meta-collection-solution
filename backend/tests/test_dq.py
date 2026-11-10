from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.datalake import DataQualityError, run_dq_checks, write_staging_parquet
from app.load_service import run_full_load
from app.models import DataSource


def test_dq_detects_null_and_duplicate_keys(tmp_path: Path):
    staging = write_staging_parquet(
        [{"id": 1, "name": "one"}, {"id": 1, "name": "duplicate"}, {"id": None, "name": "null"}],
        schema_name="main",
        table_name="orders",
        batch_id="dq-001",
        root=tmp_path / "lake",
    )

    result = run_dq_checks(staging, key_columns=["id"], expected_source_count=3)

    assert result == {
        "passed": False,
        "source_count": 3,
        "staging_count": 3,
        "null_key_count": 1,
        "duplicate_key_count": 1,
        "count_match": True,
    }


def test_full_load_quarantines_dq_failure(tmp_path: Path):
    source_path = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{source_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER, name TEXT)"))
        connection.execute(text("INSERT INTO orders(id, name) VALUES (1, 'one'), (1, 'duplicate')"))

    source = DataSource(name="fixture", db_type="sqlite", database=str(source_path), host="", username="")
    with pytest.raises(DataQualityError) as error:
        run_full_load(
            source,
            schema_name="main",
            table_name="orders",
            key_columns=["id"],
            batch_id="dq-failure",
            root=tmp_path / "lake",
        )

    assert error.value.result["duplicate_key_count"] == 1
    assert list((tmp_path / "lake" / "quarantine").rglob("*.parquet"))
    assert not (tmp_path / "lake" / "l0" / "l0.duckdb").exists()
