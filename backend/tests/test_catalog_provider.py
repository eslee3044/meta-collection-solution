from app.catalog.oracle import OracleCatalogProvider
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
