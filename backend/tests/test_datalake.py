from pathlib import Path

import pytest

from app.datalake import merge_parquet_to_l0, write_staging_parquet


def test_staging_and_l0_merge_are_idempotent_and_evolve_schema(tmp_path: Path):
    first = write_staging_parquet(
        [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}],
        schema_name="sales",
        table_name="orders",
        batch_id="20261110-01",
        root=tmp_path,
    )
    result = merge_parquet_to_l0(first, schema_name="sales", table_name="orders", key_columns=["id"], root=tmp_path)
    assert result["row_count"] == 2

    second = write_staging_parquet(
        [{"id": 2, "name": "two-updated", "amount": 20}, {"id": 3, "name": "three", "amount": 30}],
        schema_name="sales",
        table_name="orders",
        batch_id="20261110-02",
        root=tmp_path,
    )
    result = merge_parquet_to_l0(second, schema_name="sales", table_name="orders", key_columns=["id"], root=tmp_path)
    assert result["row_count"] == 3
    assert "amount" in result["columns"]

    repeated = merge_parquet_to_l0(second, schema_name="sales", table_name="orders", key_columns=["id"], root=tmp_path)
    assert repeated["row_count"] == 3


def test_datalake_rejects_unsafe_identifiers(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid table"):
        write_staging_parquet([{"id": 1}], schema_name="sales", table_name="orders;drop", batch_id="one", root=tmp_path)
