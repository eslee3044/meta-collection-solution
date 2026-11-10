from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DatalakeTableNotFound(LookupError):
    pass


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _quote(value: str, label: str) -> str:
    return '"' + _identifier(value, label).replace('"', '""') + '"'


def _database_path(root: Path) -> Path:
    return Path(root) / "l0" / "l0.duckdb"


def list_l0_tables(root: Path) -> list[dict[str, Any]]:
    database = _database_path(root)
    if not database.is_file():
        return []
    connection = duckdb.connect(str(database), read_only=True)
    try:
        tables = connection.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
        """).fetchall()
        result = []
        for schema_name, table_name in tables:
            qualified = f"{_quote(schema_name, 'schema')}.{_quote(table_name, 'table')}"
            count = connection.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()[0]
            result.append({"schema_name": schema_name, "table_name": table_name, "row_count": int(count)})
        return result
    finally:
        connection.close()


def preview_l0_table(root: Path, schema_name: str, table_name: str, *, limit: int = 100) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    schema_name = _identifier(schema_name, "schema")
    table_name = _identifier(table_name, "table")
    database = _database_path(root)
    if not database.is_file():
        raise DatalakeTableNotFound(f"L0 table does not exist: {schema_name}.{table_name}")

    connection = duckdb.connect(str(database), read_only=True)
    qualified = f"{_quote(schema_name, 'schema')}.{_quote(table_name, 'table')}"
    try:
        exists = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
            [schema_name, table_name],
        ).fetchone()[0]
        if exists != 1:
            raise DatalakeTableNotFound(f"L0 table does not exist: {schema_name}.{table_name}")
        cursor = connection.execute(f"SELECT * FROM {qualified} LIMIT ?", [limit])
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        rows = json.loads(json.dumps(rows, default=str))
        return {
            "schema_name": schema_name,
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "limit": limit,
        }
    finally:
        connection.close()
