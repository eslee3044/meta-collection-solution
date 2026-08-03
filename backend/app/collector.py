import hashlib
import json
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine
from sshtunnel import SSHTunnelForwarder

from .models import DataSource
from .security import decrypt_json
from .capabilities import assert_supported_db_type


DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306, "mariadb": 3306, "mssql": 1433, "oracle": 1521, "db2": 50000}


def _safe(call, default):
    try:
        return call()
    except (NotImplementedError, AttributeError):
        return default


def _url(source: DataSource, host: str, port: int | None) -> str:
    secret = decrypt_json(source.secret_encrypted)
    password = quote_plus(secret.get("password", ""))
    username = quote_plus(source.username)
    database = source.database
    if source.db_type == "sqlite":
        return f"sqlite:///{database}"
    if source.db_type == "bigquery":
        dataset = (source.options or {}).get("dataset", "")
        return f"bigquery://{database}/{dataset}" if dataset else f"bigquery://{database}"
    drivers = {
        "postgresql": "postgresql+psycopg",
        "mysql": "mysql+pymysql",
        "mariadb": "mysql+pymysql",
        "mssql": "mssql+pyodbc",
        "oracle": "oracle+oracledb",
        "db2": "db2+ibm_db",
    }
    if source.db_type == "mssql":
        driver = quote_plus(source.options.get("driver", "ODBC Driver 18 for SQL Server"))
        return f"{drivers[source.db_type]}://{username}:{password}@{host}:{port}/{database}?driver={driver}&TrustServerCertificate=yes"
    if source.db_type == "oracle":
        service = quote_plus(source.options.get("service_name", database))
        return f"{drivers[source.db_type]}://{username}:{password}@{host}:{port}/?service_name={service}"
    return f"{drivers[source.db_type]}://{username}:{password}@{host}:{port}/{database}"


@contextmanager
def source_engine(source: DataSource) -> Iterator[Engine]:
    tunnel = None
    engine: Engine | None = None
    key_file: Path | None = None
    host, port = source.host, source.port or DEFAULT_PORTS.get(source.db_type)
    try:
        if source.ssh_enabled:
            ssh = decrypt_json(source.ssh_secret_encrypted)
            kwargs = {
                "ssh_address_or_host": (source.ssh_host, source.ssh_port),
                "ssh_username": source.ssh_username,
                "remote_bind_address": (source.host, port),
            }
            if source.ssh_auth_type == "private_key":
                handle = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False, encoding="utf-8")
                handle.write(ssh.get("private_key", ""))
                handle.close()
                key_file = Path(handle.name)
                kwargs["ssh_pkey"] = str(key_file)
                kwargs["ssh_private_key_password"] = ssh.get("private_key_passphrase") or None
            else:
                kwargs["ssh_password"] = ssh.get("password")
            tunnel = SSHTunnelForwarder(**kwargs)
            tunnel.start()
            host, port = "127.0.0.1", tunnel.local_bind_port
        options = source.options or {}
        engine_options = {"pool_pre_ping": True, "connect_args": options.get("connect_args", {})}
        if source.db_type == "bigquery":
            secret = decrypt_json(source.secret_encrypted)
            credentials = secret.get("service_account")
            if not credentials:
                raise ValueError("BigQuery 서비스 계정 JSON이 등록되지 않았습니다.")
            engine_options["credentials_info"] = credentials
            engine_options["location"] = options.get("location", "US")
        engine = create_engine(_url(source, host, port), **engine_options)
        yield engine
    finally:
        if engine:
            engine.dispose()
        if tunnel:
            tunnel.stop()
        if key_file and key_file.exists():
            key_file.unlink()


def test_source(source: DataSource) -> None:
    assert_supported_db_type(source.db_type)
    with source_engine(source) as engine, engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _storage_metrics(connection: Connection, source: DataSource, schema_name: str) -> dict[str, dict]:
    if source.db_type == "bigquery":
        project = source.database
        location = str((source.options or {}).get("location", "US")).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{4,61}[a-z0-9]", project) or not re.fullmatch(r"[a-z0-9-]+", location):
            raise ValueError("BigQuery 프로젝트 ID 또는 리전 형식이 올바르지 않습니다.")
        query = f"""
            SELECT table_name, total_logical_bytes AS data_bytes, 0 AS index_bytes,
                   total_logical_bytes AS total_bytes, total_rows AS row_estimate
            FROM `{project}`.`region-{location}`.INFORMATION_SCHEMA.TABLE_STORAGE
            WHERE table_schema = :schema AND deleted = FALSE AND table_type = 'BASE TABLE'
        """
        rows = connection.execute(text(query), {"schema": schema_name}).mappings()
        return _rows_to_storage(rows)

    queries = {
        "postgresql": """
            SELECT c.relname AS table_name, pg_relation_size(c.oid) AS data_bytes,
                   pg_indexes_size(c.oid) AS index_bytes, pg_total_relation_size(c.oid) AS total_bytes,
                   CAST(c.reltuples AS BIGINT) AS row_estimate
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
        """,
        "mysql": """
            SELECT TABLE_NAME AS table_name, COALESCE(DATA_LENGTH, 0) AS data_bytes,
                   COALESCE(INDEX_LENGTH, 0) AS index_bytes,
                   COALESCE(DATA_LENGTH, 0) + COALESCE(INDEX_LENGTH, 0) AS total_bytes,
                   TABLE_ROWS AS row_estimate
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
        """,
        "mariadb": """
            SELECT TABLE_NAME AS table_name, COALESCE(DATA_LENGTH, 0) AS data_bytes,
                   COALESCE(INDEX_LENGTH, 0) AS index_bytes,
                   COALESCE(DATA_LENGTH, 0) + COALESCE(INDEX_LENGTH, 0) AS total_bytes,
                   TABLE_ROWS AS row_estimate
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
        """,
        "mssql": """
            SELECT t.name AS table_name,
                   SUM((p.in_row_data_page_count + p.lob_used_page_count + p.row_overflow_used_page_count) * 8192) AS data_bytes,
                   SUM((p.used_page_count - p.in_row_data_page_count - p.lob_used_page_count - p.row_overflow_used_page_count) * 8192) AS index_bytes,
                   SUM(p.reserved_page_count * 8192) AS total_bytes,
                   SUM(p.row_count) AS row_estimate
            FROM sys.dm_db_partition_stats p
            JOIN sys.tables t ON t.object_id = p.object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = :schema
            GROUP BY t.name
        """,
        "oracle": """
            SELECT t.table_name,
                   COALESCE(ds.data_bytes, 0) AS data_bytes,
                   COALESCE(ix.index_bytes, 0) AS index_bytes,
                   COALESCE(ds.data_bytes, 0) + COALESCE(ix.index_bytes, 0) AS total_bytes,
                   t.num_rows AS row_estimate
            FROM all_tables t
            LEFT JOIN (
              SELECT owner, segment_name, SUM(bytes) AS data_bytes FROM all_segments
              WHERE segment_type LIKE 'TABLE%' GROUP BY owner, segment_name
            ) ds ON ds.owner = t.owner AND ds.segment_name = t.table_name
            LEFT JOIN (
              SELECT i.table_owner, i.table_name, SUM(s.bytes) AS index_bytes
              FROM all_indexes i JOIN all_segments s ON s.owner = i.owner AND s.segment_name = i.index_name
              WHERE s.segment_type LIKE 'INDEX%' GROUP BY i.table_owner, i.table_name
            ) ix ON ix.table_owner = t.owner AND ix.table_name = t.table_name
            WHERE t.owner = :schema
        """,
        "sqlite": """
            WITH object_sizes AS (
              SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name
            )
            SELECT m.tbl_name AS table_name,
                   SUM(CASE WHEN m.type = 'table' THEN COALESCE(o.bytes, 0) ELSE 0 END) AS data_bytes,
                   SUM(CASE WHEN m.type = 'index' THEN COALESCE(o.bytes, 0) ELSE 0 END) AS index_bytes,
                   SUM(COALESCE(o.bytes, 0)) AS total_bytes,
                   NULL AS row_estimate
            FROM sqlite_master m JOIN object_sizes o ON o.name = m.name
            WHERE m.type IN ('table', 'index') AND m.tbl_name NOT LIKE 'sqlite_%'
            GROUP BY m.tbl_name
        """,
        "db2": """
            SELECT t.TABNAME AS table_name,
                   CASE WHEN t.NPAGES >= 0 THEN t.NPAGES * COALESCE(s.PAGESIZE, 4096) ELSE 0 END AS data_bytes,
                   0 AS index_bytes,
                   CASE WHEN t.FPAGES >= 0 THEN t.FPAGES * COALESCE(s.PAGESIZE, 4096) ELSE 0 END AS total_bytes,
                   CASE WHEN t.CARD >= 0 THEN t.CARD ELSE NULL END AS row_estimate
            FROM SYSCAT.TABLES t
            LEFT JOIN SYSCAT.TABLESPACES s ON s.TBSPACE = t.TBSPACE
            WHERE t.TABSCHEMA = :schema AND t.TYPE = 'T'
        """,
    }
    query = queries[source.db_type]
    rows = connection.execute(text(query), {"schema": schema_name}).mappings()
    return _rows_to_storage(rows)


def _rows_to_storage(rows) -> dict[str, dict]:
    return {
        str(row["table_name"]): {
            "data_bytes": int(row["data_bytes"] or 0),
            "index_bytes": int(row["index_bytes"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "row_estimate": int(row["row_estimate"]) if row["row_estimate"] is not None else None,
        }
        for row in rows
    }


def collect_schema(
    source: DataSource,
    selected_schemas: list[str] | None = None,
    include_storage: bool = False,
) -> tuple[dict, int, str]:
    assert_supported_db_type(source.db_type)
    with source_engine(source) as engine, engine.connect() as connection:
        inspector = inspect(engine)
        available = inspector.get_schema_names()
        configured_dataset = (source.options or {}).get("dataset") if source.db_type == "bigquery" else None
        schemas = selected_schemas or ([configured_dataset] if configured_dataset else [
            name for name in available
            if name.lower() not in {"information_schema", "pg_catalog", "sys"}
            and not (source.db_type == "db2" and name.upper().startswith("SYS"))
        ])
        result = {
            "source": source.name,
            "db_type": source.db_type,
            "database": source.database,
            "collection_options": {"basic": True, "storage_growth": include_storage},
            "schemas": [],
        }
        count = 0
        for schema_name in schemas:
            schema = {"name": schema_name, "tables": [], "views": []}
            storage_metrics = _storage_metrics(connection, source, schema_name) if include_storage else {}
            for table_name in inspector.get_table_names(schema=schema_name):
                table = {
                    "name": table_name,
                    "comment": (_safe(lambda: inspector.get_table_comment(table_name, schema=schema_name), {}) or {}).get("text"),
                    "columns": inspector.get_columns(table_name, schema=schema_name),
                    "primary_key": _safe(lambda: inspector.get_pk_constraint(table_name, schema=schema_name), {}),
                    "foreign_keys": _safe(lambda: inspector.get_foreign_keys(table_name, schema=schema_name), []),
                    "indexes": _safe(lambda: inspector.get_indexes(table_name, schema=schema_name), []),
                    "unique_constraints": _safe(lambda: inspector.get_unique_constraints(table_name, schema=schema_name), []),
                }
                if include_storage:
                    table["storage"] = storage_metrics.get(table_name, {"data_bytes": 0, "index_bytes": 0, "total_bytes": 0, "row_estimate": None})
                for column in table["columns"]:
                    column["type"] = str(column["type"])
                schema["tables"].append(table)
                count += 1
            for view_name in inspector.get_view_names(schema=schema_name):
                schema["views"].append({"name": view_name, "definition": inspector.get_view_definition(view_name, schema=schema_name)})
                count += 1
            result["schemas"].append(schema)
    raw = json.dumps(result, sort_keys=True, default=str).encode()
    return result, count, hashlib.sha256(raw).hexdigest()
