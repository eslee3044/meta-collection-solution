from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
import psycopg
from fastapi import HTTPException
from psycopg import sql
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .datalake_target_service import load_active_connection

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
            "PostgreSQL Data Plane requires a saved Datalake target or complete METAVAULT_DATALAKE_POSTGRES_* settings"
        )
    return URL.create(
        "postgresql+psycopg",
        username=settings.datalake_postgres_user,
        password=settings.datalake_postgres_password,
        host=settings.datalake_postgres_host,
        port=settings.datalake_postgres_port,
        database=settings.datalake_postgres_name,
    ).render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://", 1)


def _saved_postgres_connect_kwargs(session: Session) -> dict[str, Any] | None:
    try:
        payload = load_active_connection(session)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    return {
        "host": payload.host,
        "port": payload.port,
        "dbname": payload.database,
        "user": payload.username,
        "password": payload.password,
        "sslmode": payload.ssl_mode,
        "connect_timeout": payload.connect_timeout,
        "application_name": "metavault-datalake-publisher",
    }


def _connect_postgres():
    try:
        with SessionLocal() as session:
            kwargs = _saved_postgres_connect_kwargs(session)
        if kwargs:
            return psycopg.connect(**kwargs)
    except SQLAlchemyError:
        # Older installations may not have created datalake_targets yet.
        pass
    return psycopg.connect(_postgres_url())


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


def explain_postgresql_error(error: Exception) -> str:
    """Return an actionable Korean message without exposing connection credentials."""
    text = str(error or "")
    lower = text.lower()
    if "permission denied" in lower or "insufficientprivilege" in lower:
        return "Target PostgreSQL 계정에 스키마 또는 테이블 생성 권한이 없습니다. 대상 계정의 CREATE 권한을 확인하세요."
    if "could not connect" in lower or "connection refused" in lower or "timeout" in lower or "name or service not known" in lower:
        return "Target PostgreSQL에 연결하지 못했습니다. 대상 DB 상태와 연결 설정을 확인하세요."
    if "does not exist" in lower or "undefined table" in lower or "undefined column" in lower:
        return "Target PostgreSQL에 필요한 스키마·테이블·컬럼이 없어 DDL을 적용하지 못했습니다."
    if "already exists" in lower or "duplicate" in lower:
        return "Target PostgreSQL에 같은 객체가 이미 존재하거나 중복 제약조건이 있어 적용하지 못했습니다."
    if "syntax error" in lower or "invalid" in lower:
        return "생성된 DDL 형식이 Target PostgreSQL에서 허용되지 않았습니다. 컬럼 타입과 식별자를 확인하세요."
    return "Target PostgreSQL에 ST/L0 DDL을 적용하지 못했습니다. 대상 DB 권한과 기존 객체 상태를 확인하세요."


def apply_postgresql_ddl(ddl: str) -> dict[str, Any]:
    if not ddl.strip():
        raise ValueError("DDL is empty")
    is_plan = "CREATE SCHEMA IF NOT EXISTS" in ddl and "CREATE TABLE IF NOT EXISTS" in ddl
    is_procedure = ddl.lstrip().startswith("CREATE OR REPLACE PROCEDURE")
    if not (is_plan or is_procedure):
        raise ValueError("DDL plan is not a MetaVault ST/L0 plan or procedure script")
    with _connect_postgres() as connection:
        with connection.cursor() as cursor:
            cursor.execute(ddl)
        connection.commit()
    return {"engine": "postgresql", "status": "applied"}

def inspect_postgresql_objects(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with _connect_postgres() as connection:
        with connection.cursor() as cursor:
            results = []
            for item in objects:
                schema = _identifier(str(item["schema"]), "schema")
                table = _identifier(str(item["table"]), "table")
                procedures = [_identifier(str(name), "procedure") for name in item.get("procedures", [])]
                table_exists = bool((cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)", (schema, table)).fetchone() or (False,))[0])
                procedure_rows = cursor.execute("SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname=%s AND p.proname = ANY(%s)", (schema, procedures)).fetchall() if procedures else []
                st_schema = _identifier(str(item.get("st_schema", schema)), "schema")
                st_table = _identifier(str(item.get("st_table", table)), "table")
                st_table_exists = bool((cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)", (st_schema, st_table)).fetchone() or (False,))[0])
                results.append({"key": item["key"], "table_exists": bool(table_exists), "st_table_exists": st_table_exists, "procedures": [row[0] for row in procedure_rows], "procedure_ddls": {row[0]: row[1] for row in procedure_rows}})
            return results


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

    with _connect_postgres() as connection:
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
