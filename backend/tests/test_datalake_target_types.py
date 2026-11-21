import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.datalake_target_service import create_target, sync_meta_target_database
import app.datalake_target_service as target_service
from app.config import get_settings
from app.models import DatalakeTarget, MetaTableConfig
from app.schemas import DatalakeTargetConnectionIn


def test_bigquery_target_accepts_project_dataset_and_service_account():
    service_account = json.dumps({
        "type": "service_account",
        "project_id": "analytics-project",
        "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        "client_email": "loader@analytics-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })

    payload = DatalakeTargetConnectionIn(
        target_type="bigquery",
        project_id="analytics-project",
        dataset="metadata_lake",
        location="asia-northeast3",
        service_account_json=service_account,
    )

    assert payload.target_type == "bigquery"
    assert payload.project_id == "analytics-project"
    assert payload.dataset == "metadata_lake"
    assert payload.host is None


def test_bigquery_target_rejects_missing_service_account():
    with pytest.raises(ValidationError):
        DatalakeTargetConnectionIn(
            target_type="bigquery",
            project_id="analytics-project",
            dataset="metadata_lake",
        )


def test_redshift_target_uses_redshift_default_port():
    payload = DatalakeTargetConnectionIn(
        target_type="redshift",
        host="cluster.example.redshift.amazonaws.com",
        database="warehouse",
        username="loader",
        password="secret",
        ssl_mode="require",
    )

    assert payload.port == 5439


@pytest.mark.parametrize(
    ("target_type", "expected"),
    [("postgresql", "PostgreSQL"), ("bigquery", "BigQuery"), ("redshift", "Redshift")],
)
def test_selected_target_type_becomes_meta_registration_database(target_type, expected):
    engine = create_engine("sqlite:///:memory:")
    MetaTableConfig.__table__.create(engine)

    with Session(engine) as session:
        assert sync_meta_target_database(session, target_type) == expected
        session.commit()
        config = session.get(MetaTableConfig, 1)
        assert config is not None
        assert config.target_database_name == expected


def test_bigquery_connection_checks_dataset_and_query_without_exposing_credentials():
    service_account = json.dumps({
        "type": "service_account",
        "project_id": "analytics-project",
        "private_key": "test-key",
        "client_email": "loader@analytics-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    payload = DatalakeTargetConnectionIn(
        target_type="bigquery",
        project_id="analytics-project",
        dataset="metadata_lake",
        location="asia-northeast3",
        service_account_json=service_account,
    )
    calls = {}

    class QueryJob:
        def result(self, timeout=None):
            calls["query_timeout"] = timeout
            return [(1,)]

    class Client:
        def get_dataset(self, dataset, timeout=None):
            calls["dataset"] = dataset
            calls["dataset_timeout"] = timeout

        def query(self, statement, location=None):
            calls["query"] = statement
            calls["location"] = location
            return QueryJob()

    result = target_service.test_bigquery_connection(
        payload,
        credentials_factory=lambda info: calls.setdefault("credential_project", info["project_id"]) or object(),
        client_factory=lambda **kwargs: Client(),
    )

    assert calls["dataset"] == "analytics-project.metadata_lake"
    assert calls["query"] == "SELECT 1"
    assert calls["location"] == "asia-northeast3"
    assert result == {"success": True, "target_type": "bigquery", "permissions": {"dataset": True, "query": True}}
    assert "test-key" not in repr(result)


def test_bigquery_target_is_encrypted_and_updates_registration_default(monkeypatch):
    monkeypatch.setenv("METAVAULT_SECRET_KEY", "token-key-that-is-long-enough-for-testing-123")
    monkeypatch.setenv("METAVAULT_CREDENTIAL_ENCRYPTION_KEY", "credential-key-that-is-long-enough-456")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    DatalakeTarget.__table__.create(engine)
    MetaTableConfig.__table__.create(engine)
    service_account = json.dumps({
        "type": "service_account",
        "project_id": "analytics-project",
        "private_key": "test-key",
        "client_email": "loader@analytics-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    payload = DatalakeTargetConnectionIn(
        target_type="bigquery",
        project_id="analytics-project",
        dataset="metadata_lake",
        service_account_json=service_account,
    )

    with Session(engine) as session:
        result = create_target(session, payload, actor="admin@example.com", tester=lambda _: {"success": True})
        stored = session.query(DatalakeTarget).one()
        config = session.get(MetaTableConfig, 1)

        assert "test-key" not in stored.secret_encrypted
        assert result["connection_summary"] == {"project_id": "analytics-project", "dataset": "metadata_lake", "location": None}
        assert "service_account" not in repr(result)
        assert config is not None
        assert config.target_database_name == "BigQuery"
    get_settings.cache_clear()
