from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
import psycopg
from psycopg import sql
from sqlalchemy.engine import URL

from .config import get_settings

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DatalakePostgresConfigurationError(ValueError):
    pass


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _postgres_url() -> str:
    settings = get_settings()
    if settings.datalake_postgres_url:
        return settings.datalake_postgres_url
    values = (
        settings.datalake_postgres_host,
        settings.datalake_postgres_port,
        settings.datalake_postgres_name,
        settings.datalake_postgres_user,
        settings.datalake_postgres_password,
    )
    if any(value in (None, "") for value in values):
        raise DatalakePostgresConfigurationError(
            "PostgreSQL Data Plane requires METAVAULT_DATALAKE_POSTGRES_URL "
            "or complete METAVAULT_DATALAKE_POSTGRES_* settings"
        )
    return URL.create(
        "postgresql+psycopg",
        username=settings.datalake_postgres_user,
        password=settings.datalake_postgres_password,
        host=settings.datalake_postgres_host,
        port=settings.datalake_postgres_port,
        database=settings.datalake_postgres_name,
    ).render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://", 1)


def _postgres_type(duck_type: str) -> str:
    value = duck_type.upper()
    if value.startswith(("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UBIGINT")):
        return "BIGINT"
    if value.startswith(("DECIMAL", "NUMERIC")):
        return value.split("(", 1)[0]
    if value.startswith(("DOUBLE", "FLOAT", "REAL")):
        return "DOUBLE PRECISION"
    if value.startswith("BOOLEAN"):
        return "BOOLEAN"
    if value.startswith("DATE"):
        return "DATE"
    if value.startswith("TIMESTAMP"):
        return "TIMESTAMPTZ" if "WITH TIME ZONE" in value else "TIMESTAMP"
    if value.startswith(("BLOB", "BYTEA")):
        return "BYTEA"
    return "TEXT"


def _parquet_columns(path: Path) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    connection = duckdb.connect()
    try:
        rows = connection.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        descriptions = connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        names = [item[0] for item in descriptions]
        types = [_postgres_type(item[1]) for item in descriptions]
        return names, types, rows
    finally:
        connection.close()


def publish_parquet_to_postgres(
    parquet_path: Path,
    *,
    schema_name: str,
    table_name: str,
    key_columns: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Publish one validated ST Parquet batch to PostgreSQL L0 using an idempotent upsert."""
    schema_name = _identifier(schema_name, "schema")
    table_name = _identifier(table_name, "table")
    keys = [_identifier(column, "key column") for column in key_columns]
    if not keys:
        raise ValueError("at least one key column is required for PostgreSQL publish")
    source = Path(parquet_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".parquet":
        raise ValueError("parquet_path must point to an existing .parquet file")

    columns, types, rows = _parquet_columns(source)
    if not columns or not rows:
        raise ValueError("staging parquet must contain columns and rows")
    missing = [key for key in keys if key not in columns]
    if missing:
        raise ValueError(f"key columns are missing from staging parquet: {missing}")

    with psycopg.connect(_postgres_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}") .format(sql.Identifier(schema_name)))
            exists = cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)",
                (schema_name, table_name),
            ).fetchone()[0]
            table = sql.Identifier(schema_name, table_name)
            if not exists:
                definitions = [sql.SQL("{} {} NOT NULL").format(sql.Identifier(name), sql.SQL(type_name)) for name, type_name in zip(columns, types)]
                definitions.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, keys))))
                cursor.execute(sql.SQL("CREATE TABLE {} ({})").format(table, sql.SQL(", ").join(definitions)))
            else:
                existing = {
                    row[0]
                    for row in cursor.execute(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                        (schema_name, table_name),
                    ).fetchall()
                }
                for name, type_name in zip(columns, types):
                    if name not in existing:
                        cursor.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}") .format(table, sql.Identifier(name), sql.SQL(type_name)))

            staging = sql.Identifier(f"_metavault_stg_{table_name}_{abs(hash(str(source))) % 10_000_000}")
            definitions = [sql.SQL("{} {}") .format(sql.Identifier(name), sql.SQL(type_name)) for name, type_name in zip(columns, types)]
            cursor.execute(sql.SQL("CREATE TEMP TABLE {} ({}) ON COMMIT DROP") .format(staging, sql.SQL(", ").join(definitions)))
            placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(columns))
            cursor.executemany(sql.SQL("INSERT INTO {} ({}) VALUES ({})") .format(staging, sql.SQL(", ").join(map(sql.Identifier, columns)), placeholders), rows)
            insert_columns = sql.SQL(", ").join(map(sql.Identifier, columns))
            conflict = sql.SQL(", ").join(map(sql.Identifier, keys))
            updates = [sql.SQL("{} = EXCLUDED.{}") .format(sql.Identifier(column), sql.Identifier(column)) for column in columns if column not in keys]
            action = sql.SQL("DO NOTHING") if not updates else sql.SQL("DO UPDATE SET {}") .format(sql.SQL(", ").join(updates))
            cursor.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) {}") .format(table, insert_columns, insert_columns, staging, conflict, action))
            row_count = cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}") .format(table)).fetchone()[0]
        connection.commit()

    return {
        "engine": "postgresql",
        "table": f"{schema_name}.{table_name}",
        "row_count": int(row_count),
        "columns": columns,
    }
