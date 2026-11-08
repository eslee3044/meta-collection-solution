from fastapi import HTTPException

from app.main import apply_source
from app.models import DataSource
from app.schemas import DataSourceIn
from app.security import decrypt_json, encrypt_json


def test_imported_sources_are_tested_and_status_is_updated(monkeypatch):
    from app.main import _test_imported_sources

    connected = DataSource(name="ok", db_type="postgresql")
    failed = DataSource(name="bad", db_type="postgresql")
    sources = {1: connected, 2: failed}

    class Session:
        def get(self, model, source_id):
            return sources.get(source_id)

        def commit(self):
            return None

    def fake_test(source):
        if source is failed:
            raise RuntimeError("authentication failed")

    monkeypatch.setattr("app.main.test_source", fake_test)
    result = _test_imported_sources(Session(), [1, 2])

    assert result == {
        "tested": 2,
        "connected": 1,
        "failed": 1,
        "errors": [{"source_id": 2, "name": "bad", "error": "authentication failed"}],
    }
    assert connected.status == "connected"
    assert connected.last_tested_at is not None
    assert failed.status == "failed"
    assert failed.last_tested_at is not None


def test_reentered_password_replaces_unreadable_legacy_secret(monkeypatch):
    source = DataSource(secret_encrypted="legacy-ciphertext")
    payload = DataSourceIn(
        name="legacy-source",
        db_type="mysql",
        host="mysql.example.com",
        port=3306,
        database="sample",
        username="reader",
        password="reentered-password",
    )

    def fail_to_decrypt(_value):
        raise HTTPException(status_code=500, detail="저장된 인증 정보를 복호화할 수 없습니다.")

    monkeypatch.setattr("app.main.decrypt_json", fail_to_decrypt)

    apply_source(source, payload)

    assert decrypt_json(source.secret_encrypted)["password"] == "reentered-password"


def test_reentered_password_preserves_decryptable_ssl_secrets():
    source = DataSource(
        secret_encrypted=encrypt_json(
            {
                "password": "old-password",
                "ssl_ca_cert": "CA-CERT",
                "ssl_cert": "CLIENT-CERT",
                "ssl_key": "CLIENT-KEY",
                "service_account": {"project_id": "project"},
            }
        )
    )
    payload = DataSourceIn(
        name="ssl-source",
        db_type="mysql",
        host="mysql.example.com",
        port=3306,
        database="sample",
        username="reader",
        password="new-password",
        ssl_enabled=True,
    )

    apply_source(source, payload)

    secret = decrypt_json(source.secret_encrypted)
    assert secret == {
        "password": "new-password",
        "ssl_ca_cert": "CA-CERT",
        "ssl_cert": "CLIENT-CERT",
        "ssl_key": "CLIENT-KEY",
        "service_account": {"project_id": "project"},
    }


def test_omitted_password_preserves_existing_secret():
    source = DataSource(secret_encrypted=encrypt_json({"password": "existing-password", "ssl_ca_cert": "CA-CERT"}))
    payload = DataSourceIn(
        name="existing-source",
        db_type="mysql",
        host="mysql.example.com",
        port=3306,
        database="sample",
        username="reader",
        ssl_enabled=True,
    )

    apply_source(source, payload)

    assert decrypt_json(source.secret_encrypted) == {"password": "existing-password", "ssl_ca_cert": "CA-CERT"}
