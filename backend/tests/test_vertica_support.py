from app.capabilities import is_supported_db_type
from app.collector import DEFAULT_PORTS, _collect_procedures, _collect_select_permissions, _storage_metrics, _url, _usable_schema_names
from app.models import DataSource
from app.schemas import DataSourceIn


def test_vertica_is_supported_with_default_port():
    assert is_supported_db_type("vertica")
    assert DEFAULT_PORTS["vertica"] == 5433


def test_vertica_schema_accepts_connection_payload():
    payload = DataSourceIn(
        name="vertica-source",
        db_type="vertica",
        host="vertica.example.com",
        database="analytics",
        username="reader",
    )
    assert payload.db_type == "vertica"


def test_vertica_url_uses_sqlalchemy_vertica_python_dialect():
    source = DataSource(
        name="vertica-source",
        db_type="vertica",
        host="vertica.example.com",
        port=5433,
        database="analytics",
        username="reader",
    )
    assert _url(source, source.host, source.port).startswith(
        "vertica+vertica_python://reader:"
    )
    assert "@vertica.example.com:5433/analytics" in _url(source, source.host, source.port)


def test_vertica_storage_query_uses_projection_storage():
    captured = {}

    class Result:
        def mappings(self):
            return [{"table_name": "FACT_SALES", "data_bytes": 10, "index_bytes": 0, "total_bytes": 10, "row_estimate": None}]

    class Connection:
        def execute(self, statement, params):
            captured["query"] = str(statement)
            captured["params"] = params
            return Result()

    source = DataSource(name="vertica-source", db_type="vertica", database="analytics")
    result = _storage_metrics(Connection(), source, "PUBLIC")

    assert "v_monitor.projection_storage" in captured["query"]
    assert captured["params"] == {"schema": "PUBLIC"}
    assert result["FACT_SALES"]["total_bytes"] == 10


def test_vertica_select_permissions_query_uses_object_name():
    captured = {}

    class Result:
        def mappings(self):
            return [{"name": "FACT_SALES"}]

    class Connection:
        def execute(self, statement, params):
            captured["query"] = str(statement)
            return Result()

    source = DataSource(name="vertica-source", db_type="vertica", database="analytics", username="reader")
    permissions = _collect_select_permissions(Connection(), source, "PUBLIC")

    assert "object_name AS name" in captured["query"]
    assert "WITH RECURSIVE" in captured["query"]
    assert "object_type = 'ROLE'" in captured["query"]
    assert permissions["FACT_SALES"]["select"] is True


def test_vertica_procedure_query_uses_catalog_procedures():
    captured = {}

    class Result:
        def mappings(self):
            return [{"name": "REFRESH_FACTS", "routine_type": "PROCEDURE", "definition": "SELECT 1"}]

    class Connection:
        def execute(self, statement, params):
            captured["query"] = str(statement)
            captured["params"] = params
            return Result()

    source = DataSource(name="vertica-source", db_type="vertica", database="analytics")
    procedures = _collect_procedures(Connection(), source, "PUBLIC")

    assert "v_catalog.procedures" in captured["query"]
    assert captured["params"] == {"schema": "PUBLIC"}
    assert procedures[0]["name"] == "REFRESH_FACTS"


def test_vertica_system_schemas_are_filtered():
    names = _usable_schema_names(["PUBLIC", "v_catalog", "v_monitor", "V_INTERNAL"], DataSource(name="vertica", db_type="vertica"))
    assert names == ["PUBLIC"]
