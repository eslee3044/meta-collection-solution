from pathlib import Path

from sqlalchemy import create_engine, text

from app.catalog.preview import preview_source_permissions
from app.models import DataSource


def test_sqlite_permission_preview_returns_schema_tables_views_and_access(tmp_path: Path):
    db_path = tmp_path / "preview.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("CREATE VIEW customer_view AS SELECT id, name FROM customers"))

    source = DataSource(name="preview", db_type="sqlite", database=str(db_path), host="", username="reader")
    result = preview_source_permissions(source)

    assert result["db_type"] == "sqlite"
    assert result["status"] == "complete"
    assert result["schemas"][0]["name"] == "main"
    objects = {item["name"]: item for item in result["schemas"][0]["objects"]}
    assert objects["customers"]["object_type"] == "TABLE"
    assert objects["customers"]["select"] is True
    assert objects["customer_view"]["object_type"] == "VIEW"
    assert objects["customer_view"]["select"] is True


def test_permission_preview_reports_unknown_when_catalog_cannot_verify_permissions(monkeypatch):
    class Provider:
        def schema_names(self, connection):
            return ["dataset"]

        def table_names(self, connection, schema):
            return ["orders"]

        def view_names(self, connection, schema):
            return ["order_view"]

    class Engine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.catalog.preview.source_engine", lambda source: Engine())
    monkeypatch.setattr("app.catalog.preview.inspect", lambda engine: object())
    monkeypatch.setattr("app.catalog.preview.get_catalog_provider", lambda source, inspector: Provider())
    monkeypatch.setattr("app.catalog.preview.select_permissions", lambda connection, source, schema: {})

    source = DataSource(name="bigquery", db_type="bigquery", database="project", host="", username="reader")
    result = preview_source_permissions(source)

    assert result["status"] == "partial"
    assert result["schemas"][0]["objects"][0]["select"] is None
    assert result["schemas"][0]["objects"][0]["permission_status"] == "unknown"


def test_permission_preview_marks_missing_grant_as_denied_when_catalog_check_is_supported(monkeypatch):
    class Provider:
        def schema_names(self, connection):
            return ["public"]

        def table_names(self, connection, schema):
            return ["private_orders"]

        def view_names(self, connection, schema):
            return []

    class Engine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.catalog.preview.source_engine", lambda source: Engine())
    monkeypatch.setattr("app.catalog.preview.inspect", lambda engine: object())
    monkeypatch.setattr("app.catalog.preview.get_catalog_provider", lambda source, inspector: Provider())
    monkeypatch.setattr("app.catalog.preview.select_permissions", lambda connection, source, schema: {})

    source = DataSource(name="postgres", db_type="postgresql", database="app", host="", username="reader")
    result = preview_source_permissions(source)

    item = result["schemas"][0]["objects"][0]
    assert item["select"] is False
    assert item["permission_status"] == "denied"
