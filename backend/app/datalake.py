"""Local DuckDB + Parquet data-plane primitives for the Mac mini MVP.

The application database remains the control plane.  This module deliberately
keeps credentials and source connections out of the data-plane files: callers
provide already extracted rows, and the worker can later replace the local
path with an object-storage adapter without changing the load contract.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def datalake_root() -> Path:
    root = Path(os.getenv("METAVAULT_DATALAKE_ROOT", "/var/lib/metavault/datalake"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _identifier(value: str, label: str = "identifier") -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _quote(value: str, label: str = "identifier") -> str:
    return '"' + _identifier(value, label).replace('"', '""') + '"'


def _qualified(columns: Sequence[str], alias: str | None = None) -> str:
    prefix = f"{_quote(alias)}." if alias else ""
    return ", ".join(f"{prefix}{_quote(column, 'column')}" for column in columns)


def write_staging_parquet(
    rows: Iterable[Mapping[str, Any]],
    *,
    schema_name: str,
    table_name: str,
    batch_id: str,
    root: Path | None = None,
) -> Path:
    """Write an extracted batch as an immutable, queryable ST Parquet file."""

    schema_name = _identifier(schema_name, "schema")
    table_name = _identifier(table_name, "table")
    batch_id = str(batch_id)
    if not _BATCH_ID.fullmatch(batch_id):
        raise ValueError(f"invalid batch: {batch_id!r}")
    materialized = [dict(row) for row in rows]
    if not materialized:
        raise ValueError("cannot write an empty staging batch")
    if any(not row for row in materialized):
        raise ValueError("staging rows must contain at least one column")

    output_dir = (root or datalake_root()) / "st" / schema_name / table_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"batch-{batch_id}.parquet"
    if output.exists():
        raise FileExistsError(f"staging batch already exists: {output}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
        input_path = Path(handle.name)
        for row in materialized:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    try:
        connection = duckdb.connect()
        try:
            connection.execute(
                f"COPY (SELECT * FROM read_json_auto('{str(input_path).replace(chr(39), chr(39) + chr(39))}', records = true)) TO '{str(output).replace(chr(39), chr(39) + chr(39))}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            connection.close()
    finally:
        input_path.unlink(missing_ok=True)
    return output


def merge_parquet_to_l0(
    parquet_path: Path,
    *,
    schema_name: str,
    table_name: str,
    key_columns: Sequence[str],
    root: Path | None = None,
) -> dict[str, Any]:
    """Idempotently merge one ST batch into a persistent DuckDB L0 table."""

    source_path = Path(parquet_path).resolve()
    if not source_path.is_file() or source_path.suffix.lower() != ".parquet":
        raise ValueError("parquet_path must point to an existing .parquet file")
    schema_name = _identifier(schema_name, "schema")
    table_name = _identifier(table_name, "table")
    keys = [_identifier(column, "key column") for column in key_columns]
    if not keys:
        raise ValueError("at least one key column is required for L0 merge")

    l0_dir = (root or datalake_root()) / "l0"
    l0_dir.mkdir(parents=True, exist_ok=True)
    database_path = l0_dir / "l0.duckdb"
    connection = duckdb.connect(str(database_path))
    qualified_table = f"{_quote(schema_name, 'schema')}.{_quote(table_name, 'table')}"
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS " + _quote(schema_name, "schema"))
        source_columns = [row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(source_path)]).fetchall()]
        if not source_columns:
            raise ValueError("staging parquet contains no columns")
        missing_keys = [key for key in keys if key not in source_columns]
        if missing_keys:
            raise ValueError(f"key columns are missing from staging parquet: {missing_keys}")

        table_exists = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
            [schema_name, table_name],
        ).fetchone()[0] == 1
        if not table_exists:
            connection.execute(
                f"CREATE TABLE {qualified_table} AS SELECT * FROM read_parquet(?)",
                [str(source_path)],
            )
        else:
            existing = {row[0] for row in connection.execute("DESCRIBE " + qualified_table).fetchall()}
            for column, data_type, *_ in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(source_path)]).fetchall():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {qualified_table} ADD COLUMN {_quote(column, 'column')} {data_type}")
            assignments = ", ".join(f"{_quote(column, 'column')} = source.{_quote(column, 'column')}" for column in source_columns)
            insert_columns = _qualified(source_columns)
            insert_values = _qualified(source_columns, "source")
            join = " AND ".join(f"target.{_quote(key, 'key column')} = source.{_quote(key, 'key column')}" for key in keys)
            connection.execute(
                f"""
                MERGE INTO {qualified_table} AS target
                USING (SELECT * FROM read_parquet(?)) AS source
                ON {join}
                WHEN MATCHED THEN UPDATE SET {assignments}
                WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
                """,
                [str(source_path)],
            )
        row_count = connection.execute(f"SELECT COUNT(*) FROM {qualified_table}").fetchone()[0]
        connection.commit()
        return {"database": str(database_path), "table": f"{schema_name}.{table_name}", "row_count": row_count, "columns": source_columns}
    finally:
        connection.close()
