"""Database-specific effective SELECT privilege collection.

This module keeps permission SQL out of the collection orchestration layer.  The
public ``select_permissions`` function deliberately preserves the existing
payload shape while allowing each database to handle its own role semantics.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ..models import DataSource
from .oracle import OracleCatalogProvider


def _rows(connection: Connection, query: str, params: dict[str, str]) -> list[dict[str, Any]]:
    result = connection.execute(text(query), params).mappings()
    return [dict(row) for row in result]


def _as_permissions(rows: list[dict[str, Any]], source: DataSource) -> dict[str, dict]:
    return {
        str(row["name"]): {
            "select": True,
            "privileges": ["SELECT"],
            "checked_as": source.username or "current_user",
        }
        for row in rows
        if row.get("name") is not None
    }


_POSTGRESQL = """
    SELECT c.relname AS name
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND has_table_privilege(
            current_user,
            format('%I.%I', n.nspname, c.relname),
            'SELECT'
          )
"""

_MYSQL_DIRECT = """
    SELECT TABLE_NAME AS name
    FROM information_schema.TABLE_PRIVILEGES
    WHERE TABLE_SCHEMA = :schema
      AND PRIVILEGE_TYPE = 'SELECT'
      AND GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
    UNION
    SELECT t.TABLE_NAME AS name
    FROM information_schema.TABLES t
    WHERE t.TABLE_SCHEMA = :schema
      AND EXISTS (
            SELECT 1
            FROM information_schema.SCHEMA_PRIVILEGES p
            WHERE p.TABLE_SCHEMA = t.TABLE_SCHEMA
              AND p.PRIVILEGE_TYPE = 'SELECT'
              AND p.GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
          )
    UNION
    SELECT t.TABLE_NAME AS name
    FROM information_schema.TABLES t
    WHERE t.TABLE_SCHEMA = :schema
      AND EXISTS (
            SELECT 1
            FROM information_schema.USER_PRIVILEGES p
            WHERE p.PRIVILEGE_TYPE = 'SELECT'
              AND p.GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
          )
"""

_MYSQL_ROLE = """
    SELECT TABLE_NAME AS name
    FROM information_schema.ROLE_TABLE_GRANTS
    WHERE TABLE_SCHEMA = :schema
      AND PRIVILEGE_TYPE = 'SELECT'
"""

_MARIADB_DIRECT = """
    SELECT TABLE_NAME AS name
    FROM information_schema.TABLE_PRIVILEGES
    WHERE TABLE_SCHEMA = :schema
      AND PRIVILEGE_TYPE = 'SELECT'
      AND GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
    UNION
    SELECT t.TABLE_NAME AS name
    FROM information_schema.TABLES t
    WHERE t.TABLE_SCHEMA = :schema
      AND EXISTS (
            SELECT 1
            FROM information_schema.SCHEMA_PRIVILEGES p
            WHERE p.TABLE_SCHEMA = t.TABLE_SCHEMA
              AND p.PRIVILEGE_TYPE = 'SELECT'
              AND p.GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
          )
"""

_MARIADB_ROLE = """
    SELECT p.TABLE_NAME AS name
    FROM information_schema.TABLE_PRIVILEGES p
    JOIN information_schema.APPLICABLE_ROLES r
      ON r.ROLE_NAME = p.GRANTEE
    WHERE p.TABLE_SCHEMA = :schema
      AND p.PRIVILEGE_TYPE = 'SELECT'
      AND r.GRANTEE IN (QUOTE(CURRENT_USER()), QUOTE(USER()))
"""

_MSSQL = """
    SELECT o.name AS name
    FROM sys.objects o
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    WHERE s.name = :schema
      AND o.type IN ('U', 'V')
      AND HAS_PERMS_BY_NAME(
            QUOTENAME(s.name) + '.' + QUOTENAME(o.name),
            'OBJECT',
            'SELECT'
          ) = 1
"""

_DB2 = """
    SELECT TABNAME AS name
    FROM SYSCAT.TABAUTH
    WHERE TABSCHEMA = :schema
      AND SELECTAUTH IN ('Y', 'G', 'A')
      AND (
            GRANTEE = CURRENT USER
            OR GRANTEE = CURRENT ROLE
            OR GRANTEE = 'PUBLIC'
            OR GRANTEETYPE IN ('P', 'R', 'G')
          )
"""

_VERTICA = """
    WITH RECURSIVE role_members(role_name) AS (
        SELECT object_name
        FROM v_catalog.grants
        WHERE object_type = 'ROLE'
          AND grantee = CURRENT_USER
        UNION
        SELECT g.object_name
        FROM v_catalog.grants g
        JOIN role_members r ON g.grantee = r.role_name
        WHERE g.object_type = 'ROLE'
    ), effective_grantees(grantee) AS (
        SELECT CURRENT_USER
        UNION
        SELECT 'PUBLIC'
        UNION
        SELECT role_name FROM role_members
    )
    SELECT object_name AS name
    FROM v_catalog.grants
    WHERE object_schema = :schema
      AND object_type IN ('TABLE', 'VIEW')
      AND privilege = 'SELECT'
      AND grantee IN (SELECT grantee FROM effective_grantees)
    UNION
    SELECT table_name AS name
    FROM v_catalog.tables
    WHERE table_schema = :schema
      AND owner_name = CURRENT_USER
    UNION
    SELECT table_name AS name
    FROM v_catalog.views
    WHERE table_schema = :schema
      AND owner_name = CURRENT_USER
"""


def permission_check_supported(source: DataSource) -> bool:
    """Whether the SQL/catalog result can classify absent rows as denied."""
    return source.db_type in {"sqlite", "postgresql", "mysql", "mariadb", "mssql", "oracle", "db2", "vertica"}


def select_permissions(connection: Connection, source: DataSource, schema_name: str) -> dict[str, dict]:
    """Return effective SELECT permissions without changing the legacy payload."""
    if source.db_type == "oracle":
        return OracleCatalogProvider(source).select_permissions(connection, schema_name)
    if source.db_type == "sqlite":
        return {"*": {"select": True, "privileges": ["SELECT"], "checked_as": source.username or "sqlite"}}
    if source.db_type == "bigquery":
        # BigQuery permissions are IAM/dataset-level rather than SQL table grants.
        # Do not raise KeyError or pretend that table-level SELECT was verified.
        return {}

    queries = {
        "postgresql": _POSTGRESQL,
        "mysql": _MYSQL_DIRECT,
        "mariadb": _MARIADB_DIRECT,
        "mssql": _MSSQL,
        "db2": _DB2,
        "vertica": _VERTICA,
    }
    query = queries.get(source.db_type)
    if query is None:
        return {}

    rows = _rows(connection, query, {"schema": schema_name})
    if source.db_type == "mysql":
        # ROLE_TABLE_GRANTS exists only on supported MySQL versions.  Run it
        # independently so an older server still returns direct privileges.
        try:
            rows.extend(_rows(connection, _MYSQL_ROLE, {"schema": schema_name}))
        except SQLAlchemyError:
            pass
    elif source.db_type == "mariadb":
        # APPLICABLE_ROLES is version/configuration dependent.  Direct grants
        # must remain usable when the role catalog is unavailable.
        try:
            rows.extend(_rows(connection, _MARIADB_ROLE, {"schema": schema_name}))
        except SQLAlchemyError:
            pass
    return _as_permissions(rows, source)
