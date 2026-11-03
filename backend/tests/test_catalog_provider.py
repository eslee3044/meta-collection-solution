from app.catalog.oracle import OracleCatalogProvider
from app.catalog.registry import get_catalog_provider
from app.collector import _collect_select_permissions
from app.models import DataSource


class Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows_by_fragment):
        self.rows_by_fragment = rows_by_fragment
        self.queries = []

    def execute(self, statement, params=None):
        query = str(statement)
        self.queries.append((query, params or {}))
        for fragment, rows in self.rows_by_fragment.items():
            if fragment.lower() in query.lower():
                return Result(rows)
        return Result([])


def oracle_source():
    return DataSource(name="oracle", db_type="oracle", database="ORCL", host="db", username="reader")


def test_oracle_provider_exposes_probe_and_schema_contract():
    provider = OracleCatalogProvider(oracle_source())

    assert provider.probe_sql() == "SELECT 1 FROM DUAL"
    assert provider.schema_query().strip().startswith("SELECT username AS name")
    assert provider.stage_names() == ["procedures", "permissions", "tables", "views"]


def test_catalog_registry_keeps_inspector_fallback_and_oracle_provider():
    class Inspector:
        def get_schema_names(self):
            return ["public"]

        def get_table_names(self, schema):
            return ["records"]

        def get_view_names(self, schema):
            return ["record_view"]

    generic = get_catalog_provider(DataSource(name="pg", db_type="postgresql", database="db"), Inspector())
    assert generic.schema_names(None) == ["public"]
    assert generic.table_names(None, "public") == ["records"]
    assert generic.view_names(None, "public") == ["record_view"]

    oracle = get_catalog_provider(oracle_source(), Inspector())
    assert oracle.custom.__class__ is OracleCatalogProvider


def test_oracle_provider_collects_catalog_layers():
    provider = OracleCatalogProvider(oracle_source())
    connection = FakeConnection(
        {
            "FROM dba_tab_columns": [
                {"table_name": "CUSTOMERS", "name": "ID", "ordinal_position": 1, "type": "NUMBER", "length": None, "precision_value": 10, "scale_value": 0, "nullable": 0, "default_value": None}
            ],
            "FROM dba_procedures": [{"name": "SYNC_DATA", "routine_type": "PROCEDURE", "source_line": 1, "source_text": "CREATE OR REPLACE PROCEDURE SYNC_DATA"}],
            "FROM dba_tab_privs": [{"name": "CUSTOMERS"}],
            "FROM dba_tables": [{"name": "CUSTOMERS"}],
            "FROM dba_views": [{"name": "CUSTOMER_VIEW"}],
        }
    )

    assert provider.table_names(connection, "APP") == ["CUSTOMERS"]
    assert provider.view_names(connection, "APP") == ["CUSTOMER_VIEW"]
    columns = provider.columns(connection, "APP", "CUSTOMERS")
    assert columns[0]["type"] == "NUMBER"
    assert columns[0]["nullable"] is False
    assert provider.columns_by_schema(connection, "APP")["CUSTOMERS"][0]["name"] == "ID"
    assert provider.procedures(connection, "APP")[0]["name"] == "SYNC_DATA"
    assert provider.select_permissions(connection, "APP")["CUSTOMERS"]["select"] is True

    queries = "\n".join(query for query, _ in connection.queries).lower()
    assert "dba_tab_columns" in queries
    assert "dba_source" in queries
    assert "dba_tab_privs" in queries
    assert "session_roles" in queries


def test_mysql_permissions_include_enabled_role_grants():
    captured = {}

    class Connection:
        def execute(self, statement, params):
            captured.setdefault("queries", []).append(str(statement))

            class Result:
                def mappings(self):
                    return [{"name": "CUSTOMERS"}]

            return Result()

    source = DataSource(name="mysql", db_type="mysql", database="app", username="reader")
    permissions = _collect_select_permissions(Connection(), source, "app")

    assert any("role_table_grants" in query.lower() for query in captured["queries"])
    assert permissions["CUSTOMERS"]["select"] is True


def test_mysql_permissions_keep_direct_grants_when_role_catalog_is_unavailable():
    from sqlalchemy.exc import SQLAlchemyError

    captured = []

    class Connection:
        def execute(self, statement, params):
            query = str(statement)
            captured.append(query)
            if "ROLE_TABLE_GRANTS" in query:
                raise SQLAlchemyError("ROLE_TABLE_GRANTS is unavailable")

            class Result:
                def mappings(self):
                    return [{"name": "CUSTOMERS"}]

            return Result()

    source = DataSource(name="mysql", db_type="mysql", database="app", username="reader")
    permissions = _collect_select_permissions(Connection(), source, "app")

    assert len(captured) == 2
    assert permissions["CUSTOMERS"]["select"] is True


def test_bigquery_permissions_are_explicitly_unsupported_not_a_key_error():
    class Connection:
        def execute(self, statement, params):
            raise AssertionError("BigQuery table permission query should not execute")

    source = DataSource(name="bigquery", db_type="bigquery", database="project", username="reader")
    assert _collect_select_permissions(Connection(), source, "dataset") == {}
