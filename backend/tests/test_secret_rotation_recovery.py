from fastapi import HTTPException

from app.main import apply_source
from app.models import DataSource
from app.schemas import DataSourceIn
from app.security import decrypt_json


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
