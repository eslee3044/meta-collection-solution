import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.datalake_target_service import (
    create_target,
    load_active_connection,
    replace_target,
    target_status,
    test_postgres_connection as run_postgres_connection_test,
)
from app.models import DatalakeTarget, MetaTableConfig
from app.schemas import DatalakeTargetConnectionIn
from app.security import decrypt_credentials, encrypt_credentials


def test_datalake_credentials_are_encrypted_with_dedicated_key(monkeypatch):
    monkeypatch.setenv("METAVAULT_SECRET_KEY", "token-key-that-is-long-enough-for-testing-123")
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-456")
    get_settings.cache_clear()

    payload = {
        "host": "datalake.internal",
        "port": 5432,
        "database": "warehouse",
        "username": "loader",
        "password": "do-not-expose",
        "ssl_mode": "require",
    }
    encrypted = encrypt_credentials(payload)

    assert encrypted.startswith("v1:")
    assert "do-not-expose" not in encrypted
    assert decrypt_credentials(encrypted) == payload
    get_settings.cache_clear()


def test_credentials_saved_before_dedicated_key_remain_decryptable(monkeypatch):
    monkeypatch.setenv("METAVAULT_SECRET_KEY", "legacy-system-key-that-is-long-enough-123")
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    encrypted = encrypt_credentials({"password": "legacy-encrypted-value"})

    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "new-dedicated-key-that-is-long-enough-456")
    get_settings.cache_clear()

    assert decrypt_credentials(encrypted) == {"password": "legacy-encrypted-value"}
    get_settings.cache_clear()


def test_create_target_encrypts_all_connection_fields_and_returns_no_secret(monkeypatch):
    monkeypatch.setenv("METAVAULT_SECRET_KEY", "token-key-that-is-long-enough-for-testing-123")
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-456")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    DatalakeTarget.__table__.create(engine)
    MetaTableConfig.__table__.create(engine)
    payload = DatalakeTargetConnectionIn(
        target_type="postgresql",
        host="datalake.internal",
        port=5432,
        database="warehouse",
        username="loader",
        password="do-not-expose",
        ssl_mode="require",
    )
    tested = []

    with Session(engine) as session:
        result = create_target(
            session,
            payload,
            actor="admin@example.com",
            tester=lambda value: tested.append(value) or {
                "success": True,
                "server_version": "16",
                "permissions": {"temporary_table": True},
            },
        )
        row = session.scalar(select(DatalakeTarget))

        assert row is not None
        assert tested == [payload]
        assert row.secret_encrypted.startswith("v1:")
        for secret_value in (payload.host, payload.database, payload.username, payload.password):
            assert secret_value not in row.secret_encrypted
        assert result["configured"] is True
        assert result["target_type"] == "postgresql"
        meta_config = session.get(MetaTableConfig, 1)
        assert meta_config is not None
        assert meta_config.target_database_name == "PostgreSQL"
        assert "host" not in result
        assert "database" not in result
        assert "username" not in result
        assert "password" not in result
        assert target_status(session)["credential_configured"] is True
    get_settings.cache_clear()


def test_failed_replacement_keeps_existing_encrypted_credentials(monkeypatch):
    monkeypatch.setenv("METAVAULT_SECRET_KEY", "token-key-that-is-long-enough-for-testing-123")
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-456")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    DatalakeTarget.__table__.create(engine)
    old_secret = encrypt_credentials({"host": "old.internal", "password": "old-secret"})

    with Session(engine) as session:
        item = DatalakeTarget(
            target_type="postgresql",
            secret_encrypted=old_secret,
            credential_version=3,
            status="connected",
            is_active=True,
        )
        session.add(item)
        session.commit()
        replacement = DatalakeTargetConnectionIn(
            target_type="postgresql",
            host="new.internal",
            port=5432,
            database="warehouse",
            username="loader",
            password="new-secret",
            ssl_mode="require",
        )

        with pytest.raises(HTTPException):
            replace_target(
                session,
                replacement,
                actor="admin@example.com",
                tester=lambda _: {"success": False},
            )
        session.refresh(item)
        assert item.secret_encrypted == old_secret
        assert item.credential_version == 3
    get_settings.cache_clear()


def test_postgres_connection_uses_input_but_returns_only_safe_diagnostics():
    calls = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement, parameters=None):
            calls.setdefault("statements", []).append((str(statement), parameters))
            self.last_statement = str(statement)
            return self

        def fetchone(self):
            if "has_database_privilege" in self.last_statement:
                return (True,)
            return ("16.4",)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return FakeCursor()

        def rollback(self):
            calls["rolled_back"] = True

    def connector(**kwargs):
        calls["kwargs"] = kwargs
        return FakeConnection()

    payload = DatalakeTargetConnectionIn(
        target_type="postgresql",
        host="datalake.internal",
        port=5432,
        database="warehouse",
        username="loader",
        password="do-not-expose",
        ssl_mode="require",
        connect_timeout=4,
    )
    result = run_postgres_connection_test(payload, connector=connector)

    assert calls["kwargs"]["host"] == payload.host
    assert calls["kwargs"]["password"] == payload.password
    assert calls["kwargs"]["connect_timeout"] == 4
    assert calls["rolled_back"] is True
    assert result == {
        "success": True,
        "server_version": "16.4",
        "permissions": {"create_schema": True, "temporary_table": True, "write": True, "truncate": True},
    }
    rendered = repr(result)
    for secret_value in (payload.host, payload.database, payload.username, payload.password):
        assert secret_value not in rendered


def test_failed_target_is_not_available_to_postgres_publisher(monkeypatch):
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-789")
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
            status="failed",
            is_active=True,
        ))
        session.commit()

        with pytest.raises(HTTPException) as error:
            load_active_connection(session)

    assert error.value.status_code == 409
    assert "연결 상태" in str(error.value.detail)
    get_settings.cache_clear()
