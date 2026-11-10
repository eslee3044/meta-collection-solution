from pathlib import Path

import pytest

from app.datalake_postgres import (
    DatalakePostgresConfigurationError,
    _postgres_type,
    publish_parquet_to_postgres,
)
from app.config import get_settings
from app.datalake import write_staging_parquet


def test_postgres_type_mapping_is_conservative():
    assert _postgres_type("BIGINT") == "BIGINT"
    assert _postgres_type("DOUBLE") == "DOUBLE PRECISION"
    assert _postgres_type("TIMESTAMP WITH TIME ZONE") == "TIMESTAMPTZ"
    assert _postgres_type("VARCHAR") == "TEXT"


def test_postgres_publish_requires_explicit_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("METAVAULT_DATALAKE_POSTGRES_URL", "")
    get_settings.cache_clear()
    for key in (
        "METAVAULT_DATALAKE_POSTGRES_HOST",
        "METAVAULT_DATALAKE_POSTGRES_PORT",
        "METAVAULT_DATALAKE_POSTGRES_NAME",
        "METAVAULT_DATALAKE_POSTGRES_USER",
        "METAVAULT_DATALAKE_POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    parquet = write_staging_parquet(
        [{"id": 1, "name": "one"}],
        schema_name="sales",
        table_name="orders",
        batch_id="config-test",
        root=tmp_path,
    )
    with pytest.raises(DatalakePostgresConfigurationError):
        publish_parquet_to_postgres(
            parquet,
            schema_name="sales",
            table_name="orders",
            key_columns=["id"],
        )
    get_settings.cache_clear()
