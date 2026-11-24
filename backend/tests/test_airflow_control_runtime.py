from types import SimpleNamespace

from app import airflow_control


def test_sqlite_source_runtime_does_not_require_database_credentials(monkeypatch):
    requests = []

    def fake_request(method, path, payload=None):
        requests.append((method, path, payload))
        if method == "GET":
            return 404, None
        return 200, {}

    monkeypatch.setattr(airflow_control, "_request", fake_request)
    source = SimpleNamespace(
        id=1,
        name="Sample Commerce DB",
        db_type="sqlite",
        host="",
        port=None,
        database="/app/sample/sample.db",
        username="",
        secret_encrypted="",
    )

    result = airflow_control.prepare_source_runtime(
        source=source,
        credential_mode="metadata",
        dedicated_username=None,
        dedicated_password=None,
        pool_slots=2,
        confirm_pool_resize=False,
    )

    assert result["status"] == "READY"
    connection_payload = next(payload for method, path, payload in requests if method == "POST" and path == "connections")
    assert connection_payload["conn_type"] == "sqlite"
    assert connection_payload["schema"] == "/app/sample/sample.db"
    assert connection_payload["login"] == ""
    assert connection_payload["password"] == ""
