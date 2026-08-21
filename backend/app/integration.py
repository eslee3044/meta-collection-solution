from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Engine, text


def snapshot_summary(snapshot: Any) -> dict[str, Any]:
    payload = snapshot.payload or {}
    schemas = payload.get("schemas", [])
    return {
        "id": snapshot.id,
        "data_source_id": snapshot.data_source_id,
        "run_id": snapshot.run_id,
        "captured_at": snapshot.captured_at,
        "fingerprint": snapshot.fingerprint,
        "source": payload.get("source"),
        "db_type": payload.get("db_type"),
        "database": payload.get("database"),
        "schema_count": len(schemas),
        "table_count": sum(len(schema.get("tables", [])) for schema in schemas),
        "view_count": sum(len(schema.get("views", [])) for schema in schemas),
        "procedure_count": sum(len(schema.get("procedures", [])) for schema in schemas),
        "skipped_schemas": payload.get("skipped_schemas", []),
    }


def _objects(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for schema in payload.get("schemas", []):
        schema_name = schema.get("name", "")
        schema_key = f"schema:{schema_name}"
        objects[schema_key] = {"kind": "schema", "schema": schema_name, "name": schema_name}
        for table in schema.get("tables", []):
            table_name = table.get("name", "")
            table_key = f"table:{schema_name}.{table_name}"
            table_value = dict(table)
            table_value.pop("columns", None)
            table_value.pop("indexes", None)
            objects[table_key] = {"kind": "table", "schema": schema_name, "name": table_name, "value": table_value}
            for column in table.get("columns", []):
                name = column.get("name", "")
                objects[f"column:{schema_name}.{table_name}.{name}"] = {
                    "kind": "column", "schema": schema_name, "table": table_name, "name": name, "value": column,
                }
            for index in table.get("indexes", []):
                name = index.get("name", "")
                objects[f"index:{schema_name}.{table_name}.{name}"] = {
                    "kind": "index", "schema": schema_name, "table": table_name, "name": name, "value": index,
                }
        for view in schema.get("views", []):
            name = view.get("name", "")
            objects[f"view:{schema_name}.{name}"] = {"kind": "view", "schema": schema_name, "name": name, "value": view}
        for procedure in schema.get("procedures", []):
            name = procedure.get("name", "")
            objects[f"procedure:{schema_name}.{name}"] = {"kind": "procedure", "schema": schema_name, "name": name, "value": procedure}
    return objects


def snapshot_diff(before: Any, after: Any) -> dict[str, Any]:
    old = _objects(before.payload or {})
    new = _objects(after.payload or {})
    added, removed, changed = [], [], []
    for key in sorted(new.keys() - old.keys()):
        added.append({"key": key, **new[key]})
    for key in sorted(old.keys() - new.keys()):
        removed.append({"key": key, **old[key]})
    for key in sorted(new.keys() & old.keys()):
        if new[key].get("value") != old[key].get("value"):
            changed.append({"key": key, "kind": new[key]["kind"], "before": old[key].get("value"), "after": new[key].get("value"), **{k: new[key][k] for k in ("schema", "table", "name") if k in new[key]}})
    return {
        "from_snapshot_id": before.id,
        "to_snapshot_id": after.id,
        "from_captured_at": before.captured_at,
        "to_captured_at": after.captured_at,
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def ensure_integration_views(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    statements = [
        "CREATE SCHEMA IF NOT EXISTS integration",
        """CREATE OR REPLACE VIEW integration.snapshot_history AS
           SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at, ss.fingerprint,
                  (ss.payload::jsonb)->>'source' AS source_name, (ss.payload::jsonb)->>'db_type' AS db_type,
                  jsonb_array_length(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) AS schema_count
           FROM schema_snapshots ss""",
        """CREATE OR REPLACE VIEW integration.latest_snapshots AS
           SELECT DISTINCT ON (data_source_id) snapshot_id, data_source_id, run_id, captured_at,
                  fingerprint, source_name, db_type, schema_count
           FROM integration.snapshot_history
           ORDER BY data_source_id, captured_at DESC, snapshot_id DESC""",
        """CREATE OR REPLACE VIEW integration.schema_history AS
           SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
                  schema_item->>'name' AS schema_name,
                  jsonb_array_length(COALESCE(schema_item->'tables', '[]'::jsonb)) AS table_count,
                  jsonb_array_length(COALESCE(schema_item->'views', '[]'::jsonb)) AS view_count,
                  jsonb_array_length(COALESCE(schema_item->'procedures', '[]'::jsonb)) AS procedure_count
           FROM schema_snapshots ss
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item""",
        """CREATE OR REPLACE VIEW integration.table_history AS
           SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
                  schema_item->>'name' AS schema_name, table_item->>'name' AS table_name,
                  table_item->>'comment' AS comment
           FROM schema_snapshots ss
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE(schema_item->'tables', '[]'::jsonb)) table_item""",
        """CREATE OR REPLACE VIEW integration.column_history AS
           SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
                  schema_item->>'name' AS schema_name, table_item->>'name' AS table_name,
                  column_item->>'name' AS column_name, column_item->>'type' AS data_type,
                  (column_item->>'nullable')::boolean AS nullable
           FROM schema_snapshots ss
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE(schema_item->'tables', '[]'::jsonb)) table_item
           CROSS JOIN LATERAL jsonb_array_elements(COALESCE(table_item->'columns', '[]'::jsonb)) column_item""",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
