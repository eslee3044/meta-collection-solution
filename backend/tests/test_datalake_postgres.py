from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.datalake_postgres import (
    DatalakePostgresConfigurationError,
    _postgres_type,
    _saved_postgres_connect_kwargs,
    apply_postgresql_ddl,
    publish_parquet_to_postgres,
)
from app.models import DatalakeTarget
from app.security import encrypt_credentials
from app.config import get_settings
from app.datalake import write_staging_parquet


def test_apply_postgresql_ddl_accepts_table_only_st_l0_plan(monkeypatch: pytest.MonkeyPatch):
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement):
            executed.append(statement)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

        def commit(self):
            executed.append("COMMIT")

    monkeypatch.setattr("app.datalake_postgres._connect_postgres", lambda: Connection())
    result = apply_postgresql_ddl(
        'CREATE SCHEMA IF NOT EXISTS "ST_TEST"; '
        'CREATE TABLE IF NOT EXISTS "ST_TEST"."CUSTOMERS" ("ID" BIGINT); '
        'CREATE TABLE IF NOT EXISTS "L0_TEST"."CUSTOMERS" ("ID" BIGINT);'
    )

    assert result == {"engine": "postgresql", "status": "applied"}
    assert executed[-1] == "COMMIT"



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


def test_saved_target_returns_psycopg_kwargs_without_connection_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-456")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    DatalakeTarget.__table__.create(engine)
    with Session(engine) as session:
        session.add(DatalakeTarget(
            target_type="postgresql",
            secret_encrypted=encrypt_credentials({
                "target_type": "postgresql",
                "host": "datalake.internal",
                "port": 5432,
                "database": "warehouse",
                "username": "loader",
                "password": "secret",
                "ssl_mode": "require",
                "connect_timeout": 5,
            }),
            status="connected",
            is_active=True,
        ))
        session.commit()

        kwargs = _saved_postgres_connect_kwargs(session)

    assert kwargs == {
        "host": "datalake.internal",
        "port": 5432,
        "dbname": "warehouse",
        "user": "loader",
        "password": "secret",
        "sslmode": "require",
        "connect_timeout": 5,
        "application_name": "metavault-datalake-publisher",
    }
    assert "url" not in kwargs
    get_settings.cache_clear()
