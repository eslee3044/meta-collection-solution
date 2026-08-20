from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.collector import available_schema_names, collect_schema
from app.models import DataSource


def test_available_schema_names_returns_user_selectable_sqlite_schemas(tmp_path):
    path = tmp_path / "schemas.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text("create table customers (id integer primary key)"))

    source = DataSource(name="sample", db_type="sqlite", database=str(path), host="", username="")

    assert available_schema_names(source) == ["main"]


def test_collect_schema_skips_inaccessible_schema(monkeypatch):
    class Inspector:
        def get_schema_names(self):
            return ["app", "performance_schema"]

        def get_table_names(self, schema=None):
            if schema == "performance_schema":
                raise SQLAlchemyError("access denied")
            return []

    class ConnectionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class EngineContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect(self):
            return ConnectionContext()

    import app.collector as collector
    monkeypatch.setattr(collector, "source_engine", lambda source: EngineContext())
    monkeypatch.setattr(collector, "inspect", lambda engine: Inspector())

    source = DataSource(name="sample", db_type="mysql", database="app", host="db", username="user")
    payload, count, fingerprint = collect_schema(source, selected_schemas=["app", "performance_schema"], selected_items=["TABLE"])

    assert [schema["name"] for schema in payload["schemas"]] == ["app"]
    assert payload["skipped_schemas"] == [{"name": "performance_schema", "reason": "접근 권한이 없거나 메타데이터를 조회할 수 없습니다."}]
    assert count == 0
    assert len(fingerprint) == 64
