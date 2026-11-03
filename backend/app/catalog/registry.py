"""Catalog provider registry and compatibility adapter.

The adapter lets the orchestration layer select one provider per database while
keeping the existing SQLAlchemy Inspector behaviour for databases that do not
yet need a custom catalog implementation.
"""

from typing import Any

from sqlalchemy.engine import Connection

from ..models import DataSource
from .oracle import OracleCatalogProvider


class CatalogProviderAdapter:
    def __init__(self, source: DataSource, inspector: Any):
        self.source = source
        self.inspector = inspector
        self.custom = OracleCatalogProvider(source) if source.db_type == "oracle" else None

    def schema_names(self, connection: Connection) -> list[str]:
        if self.custom:
            return self.custom.schema_names(connection)
        return list(self.inspector.get_schema_names())

    def table_names(self, connection: Connection, schema_name: str) -> list[str]:
        if self.custom:
            return self.custom.table_names(connection, schema_name)
        return list(self.inspector.get_table_names(schema=schema_name))

    def view_names(self, connection: Connection, schema_name: str) -> list[str]:
        if self.custom:
            return self.custom.view_names(connection, schema_name)
        return list(self.inspector.get_view_names(schema=schema_name))

    def columns_by_schema(self, connection: Connection, schema_name: str) -> dict[str, list[dict]]:
        if self.custom:
            return self.custom.columns_by_schema(connection, schema_name)
        return {}



def get_catalog_provider(source: DataSource, inspector: Any) -> CatalogProviderAdapter:
    return CatalogProviderAdapter(source, inspector)
