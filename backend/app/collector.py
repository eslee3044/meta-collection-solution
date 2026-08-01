import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sshtunnel import SSHTunnelForwarder

from .models import DataSource
from .security import decrypt_json


DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306, "mariadb": 3306, "mssql": 1433, "oracle": 1521}


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
    drivers = {
        "postgresql": "postgresql+psycopg",
        "mysql": "mysql+pymysql",
        "mariadb": "mysql+pymysql",
        "mssql": "mssql+pyodbc",
        "oracle": "oracle+oracledb",
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
        engine = create_engine(_url(source, host, port), pool_pre_ping=True, connect_args=options.get("connect_args", {}))
        yield engine
        engine.dispose()
    finally:
        if tunnel:
            tunnel.stop()
        if key_file and key_file.exists():
            key_file.unlink()


def test_source(source: DataSource) -> None:
    with source_engine(source) as engine, engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def collect_schema(source: DataSource, selected_schemas: list[str] | None = None) -> tuple[dict, int, str]:
    with source_engine(source) as engine:
        inspector = inspect(engine)
        available = inspector.get_schema_names()
        schemas = selected_schemas or [name for name in available if name not in {"information_schema", "pg_catalog", "sys"}]
        result = {"source": source.name, "db_type": source.db_type, "database": source.database, "schemas": []}
        count = 0
        for schema_name in schemas:
            schema = {"name": schema_name, "tables": [], "views": []}
            for table_name in inspector.get_table_names(schema=schema_name):
                table = {
                    "name": table_name,
                    "comment": (_safe(lambda: inspector.get_table_comment(table_name, schema=schema_name), {}) or {}).get("text"),
                    "columns": inspector.get_columns(table_name, schema=schema_name),
                    "primary_key": inspector.get_pk_constraint(table_name, schema=schema_name),
                    "foreign_keys": inspector.get_foreign_keys(table_name, schema=schema_name),
                    "indexes": inspector.get_indexes(table_name, schema=schema_name),
                    "unique_constraints": _safe(lambda: inspector.get_unique_constraints(table_name, schema=schema_name), []),
                }
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
