"""Read-only connection preview for schema/table/view access checks."""

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from ..collector import SYSTEM_SCHEMAS, _usable_schema_names, source_engine
from ..models import DataSource
from .permissions import permission_check_supported, select_permissions
from .registry import get_catalog_provider


def _object_access(name: str, object_type: str, permissions: dict[str, dict], permissions_supported: bool) -> dict[str, Any]:
    permission = permissions.get(name, permissions.get("*"))
    if permission is None and permissions_supported:
        return {
            "name": name,
            "object_type": object_type,
            "select": False,
            "permission_status": "denied",
            "privileges": [],
            "checked_as": "current_user",
        }
    if permission is None:
        return {
            "name": name,
            "object_type": object_type,
            "select": None,
            "permission_status": "unknown",
            "privileges": [],
            "checked_as": "not_verified",
        }
    return {
        "name": name,
        "object_type": object_type,
        "select": permission.get("select"),
        "permission_status": "granted" if permission.get("select") is True else "denied",
        "privileges": permission.get("privileges", []),
        "checked_as": permission.get("checked_as", "current_user"),
    }


def preview_source_permissions(source: DataSource) -> dict[str, Any]:
    """Inspect a source without persisting it and return object-level access."""
    schemas: list[dict[str, Any]] = []
    with source_engine(source) as engine, engine.connect() as connection:
        inspector = inspect(engine)
        provider = get_catalog_provider(source, inspector)
        available = provider.schema_names(connection)
        schema_names = _usable_schema_names(available, source)
        if source.db_type == "bigquery":
            configured_dataset = (source.options or {}).get("dataset")
            if configured_dataset:
                schema_names = [configured_dataset]
        for schema_name in schema_names:
            table_names = provider.table_names(connection, schema_name)
            view_names = provider.view_names(connection, schema_name)
            permissions = select_permissions(connection, source, schema_name)
            permissions_supported = permission_check_supported(source)
            objects = [
                *(_object_access(name, "TABLE", permissions, permissions_supported) for name in table_names),
                *(_object_access(name, "VIEW", permissions, permissions_supported) for name in view_names),
            ]
            schemas.append({
                "name": schema_name,
                "object_count": len(objects),
                "granted_count": sum(item["select"] is True for item in objects),
                "denied_count": sum(item["select"] is False for item in objects),
                "unknown_count": sum(item["select"] is None for item in objects),
                "objects": objects,
            })
    unknown_count = sum(item["unknown_count"] for item in schemas)
    status = "partial" if unknown_count else "complete"
    return {
        "status": status,
        "db_type": source.db_type,
        "database": source.database,
        "schema_count": len(schemas),
        "object_count": sum(item["object_count"] for item in schemas),
        "granted_count": sum(item["granted_count"] for item in schemas),
        "denied_count": sum(item["denied_count"] for item in schemas),
        "unknown_count": unknown_count,
        "schemas": schemas,
    }
