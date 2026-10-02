from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..models import DataSource
from .base import CatalogProvider


class OracleCatalogProvider:
    """Oracle DBA catalog access separated from the collection orchestration."""

    def __init__(self, source: DataSource):
        self.source = source

    def probe_sql(self) -> str:
        return "SELECT 1 FROM DUAL"

    def stage_names(self) -> list[str]:
        return ["procedures", "permissions", "tables", "views"]

    def schema_query(self) -> str:
        return "SELECT username AS name FROM dba_users ORDER BY username"

    def _rows(self, connection: Connection, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        mapped = connection.execute(text(query), params or {}).mappings()
        rows = mapped.all() if hasattr(mapped, "all") else mapped
        return [dict(row) for row in rows]

    def schema_names(self, connection: Connection) -> list[str]:
        return sorted({str(row["name"]).upper() for row in self._rows(connection, self.schema_query())})

    def table_names(self, connection: Connection, schema_name: str) -> list[str]:
        rows = self._rows(
            connection,
            """
            SELECT table_name AS name
            FROM dba_tables
            WHERE owner = UPPER(:schema)
            ORDER BY table_name
            """,
            {"schema": schema_name},
        )
        return [str(row["name"]) for row in rows]

    def view_names(self, connection: Connection, schema_name: str) -> list[str]:
        rows = self._rows(
            connection,
            """
            SELECT view_name AS name
            FROM dba_views
            WHERE owner = UPPER(:schema)
            ORDER BY view_name
            """,
            {"schema": schema_name},
        )
        return [str(row["name"]) for row in rows]

    def columns(self, connection: Connection, schema_name: str, table_name: str) -> list[dict]:
        rows = self._rows(
            connection,
            """
            SELECT table_name,
                   column_name AS name,
                   column_id AS ordinal_position,
                   data_type AS type,
                   data_length AS length,
                   data_precision AS precision_value,
                   data_scale AS scale_value,
                   CASE WHEN nullable = 'Y' THEN 1 ELSE 0 END AS nullable,
                   data_default AS default_value
            FROM dba_tab_columns
            WHERE owner = UPPER(:schema)
              AND table_name = UPPER(:table)
            ORDER BY column_id
            """,
            {"schema": schema_name, "table": table_name},
        )
        return [self._normalize_column({**row, "precision": row.get("precision_value"), "scale": row.get("scale_value")}) for row in rows]

    def columns_by_schema(self, connection: Connection, schema_name: str) -> dict[str, list[dict]]:
        rows = self._rows(
            connection,
            """
            SELECT table_name,
                   column_name AS name,
                   column_id AS ordinal_position,
                   data_type AS type,
                   data_length AS length,
                   data_precision AS precision_value,
                   data_scale AS scale_value,
                   CASE WHEN nullable = 'Y' THEN 1 ELSE 0 END AS nullable,
                   data_default AS default_value
            FROM dba_tab_columns
            WHERE owner = UPPER(:schema)
            ORDER BY table_name, column_id
            """,
            {"schema": schema_name},
        )
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            table_name = str(row.pop("table_name"))
            grouped.setdefault(table_name, []).append(self._normalize_column({**row, "precision": row.get("precision_value"), "scale": row.get("scale_value")}))
        return grouped

    def procedures(self, connection: Connection, schema_name: str) -> list[dict]:
        rows = self._rows(
            connection,
            """
            SELECT p.object_name AS name,
                   p.object_type AS routine_type,
                   s.line AS source_line,
                   s.text AS source_text
            FROM dba_procedures p
            LEFT JOIN dba_source s
              ON s.owner = p.owner
             AND s.name = p.object_name
             AND s.type = CASE WHEN p.object_type = 'PACKAGE' THEN 'PACKAGE BODY' ELSE p.object_type END
            WHERE p.owner = UPPER(:schema)
              AND p.object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE')
            ORDER BY p.object_name, s.line
            """,
            {"schema": schema_name},
        )
        grouped: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (str(row["name"]), str(row["routine_type"]))
            item = grouped.setdefault(key, {"name": row["name"], "routine_type": row["routine_type"], "_source": []})
            if row.get("source_text") is not None:
                item["_source"].append(str(row["source_text"]))
            elif row.get("definition") is not None:
                item["_source"].append(str(row["definition"]))
        result = []
        for item in grouped.values():
            source_lines = item.pop("_source")
            item["definition"] = "".join(source_lines) if source_lines else None
            result.append(item)
        return result

    def select_permissions(self, connection: Connection, schema_name: str) -> dict[str, dict]:
        rows = self._rows(
            connection,
            """
            SELECT table_name AS name
            FROM dba_tab_privs
            WHERE owner = UPPER(:schema) AND privilege = 'SELECT' AND (grantee = USER OR grantee = 'PUBLIC')
            UNION
            SELECT table_name AS name
            FROM dba_tables
            WHERE owner = UPPER(:schema) AND owner = USER
            UNION
            SELECT view_name AS name
            FROM dba_views
            WHERE owner = UPPER(:schema) AND owner = USER
            """,
            {"schema": schema_name},
        )
        return {
            str(row["name"]): {
                "select": True,
                "privileges": ["SELECT"],
                "checked_as": self.source.username or "current_user",
            }
            for row in rows
        }

    @staticmethod
    def _normalize_column(column: dict) -> dict:
        normalized = dict(column)
        normalized.pop("table_name", None)
        normalized.pop("precision_value", None)
        normalized.pop("scale_value", None)
        normalized["name"] = str(normalized.get("name") or "")
        normalized["type"] = str(normalized.get("type") or "").strip().upper()
        if "nullable" in normalized:
            normalized["nullable"] = bool(normalized["nullable"])
        return normalized
