"""Pure safety classification for registered ST/L0 schema migrations.

This module deliberately performs no database I/O. Target inspection and DDL
execution belong to the PostgreSQL adapter and must pass this classifier's
explicit, non-null row-count evidence before selecting an execution path.
"""
from __future__ import annotations

from typing import Any, Sequence
import re


def classify_target_state(*, st_exists: bool, l0_exists: bool, st_rows: int | None, l0_rows: int | None) -> dict[str, Any]:
    """Classify physical ST/L0 pair without treating unknown as empty."""
    if not st_exists and not l0_exists:
        return {"status": "READY", "route": "CREATE_NEW", "initial_load_required": True, "reason": "ST/L0 테이블이 아직 없습니다."}
    if st_exists != l0_exists:
        return {"status": "BLOCKED", "route": "BLOCKED", "initial_load_required": None, "reason": "ST/L0 중 한쪽만 존재합니다. 대상 상태를 먼저 복구·확인해야 합니다."}
    counts = (st_rows, l0_rows)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        return {"status": "BLOCKED", "route": "BLOCKED", "initial_load_required": None, "reason": "두 테이블의 실제 행 수를 확인할 수 없습니다. 조회 실패를 빈 테이블로 간주하지 않습니다."}
    if st_rows == 0 and l0_rows == 0:
        return {"status": "READY", "route": "APPLY_EMPTY", "initial_load_required": False, "reason": "양쪽 테이블이 비어 있습니다. 초기 적재 없이 직접 변경할 수 있습니다."}
    return {"status": "REVIEW_REQUIRED", "route": "TOBE_REQUIRED", "initial_load_required": True, "reason": "ST/L0 중 하나 이상에 데이터가 있습니다. TO-BE 생성·검증 후 운영 전환이 필요합니다."}


def compare_table_layouts(before: Sequence[dict[str, Any]], after: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compare ordered canonical column descriptions and return safe capabilities."""
    def normalize(columns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        seen: set[str] = set()
        for item in columns:
            name = str(item.get("name") or item.get("column_name") or "").strip().upper()
            if not name or name in seen:
                raise ValueError("컬럼 이름이 비었거나 중복되었습니다.")
            seen.add(name)
            raw_type = str(item.get("type") or item.get("data_type") or "").upper()
            raw_type = re.sub(r"\s+", " ", raw_type).strip()
            raw_type = raw_type.replace("CHARACTER VARYING", "VARCHAR").replace("CHARACTER(", "CHAR(")
            raw_type = raw_type.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ").replace("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP")
            normalized.append({
                "name": name,
                "type": raw_type,
                "nullable": bool(item.get("nullable", str(item.get("null_yn", "Y")).upper() != "N")),
                "length": item.get("length", item.get("data_length")),
                "precision": item.get("precision", item.get("data_precision")),
                "scale": item.get("scale", item.get("data_scale")),
            })
        return normalized

    left, right = normalize(before), normalize(after)
    left_by_name = {item["name"]: item for item in left}
    right_by_name = {item["name"]: item for item in right}
    added = [item for item in right if item["name"] not in left_by_name]
    removed = [item for item in left if item["name"] not in right_by_name]
    changed = [{"name": item["name"], "before": left_by_name[item["name"]], "after": item}
               for item in right if item["name"] in left_by_name and left_by_name[item["name"]] != item]
    left_order = [item["name"] for item in left if item["name"] in right_by_name]
    right_order = [item["name"] for item in right if item["name"] in left_by_name]
    order_changed = left_order != right_order
    added_names = {item["name"] for item in added}
    added_in_middle = bool(added_names) and [item["name"] for item in right[:-len(added_names)]] != [item["name"] for item in left]
    alter_compatible = not removed and not changed and not order_changed and not added_in_middle and all(item["nullable"] for item in added)
    return {"added": added, "removed": removed, "changed_columns": changed, "order_changed": order_changed,
            "added_in_middle": added_in_middle, "changed": bool(added or removed or changed or order_changed), "alter_compatible": alter_compatible,
            "requires_rebuild": bool(removed or changed or order_changed or (added and not alter_compatible))}


def build_migration_status(*, identity: dict[str, Any], strategy: str, desired_pk_columns: list[str], st: dict[str, str], l0: dict[str, str],
                           desired: list[dict[str, Any]], physical: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only ST/L0-vs-metadata comparison response."""
    objects = physical.get("objects", [])
    if len(objects) != 2:
        raise ValueError("ST/L0 구조 비교 결과가 올바르지 않습니다.")
    state = classify_target_state(
        st_exists=objects[0]["exists"], l0_exists=objects[1]["exists"],
        st_rows=(0 if objects[0].get("has_rows") is False else 1 if objects[0].get("has_rows") is True else None),
        l0_rows=(0 if objects[1].get("has_rows") is False else 1 if objects[1].get("has_rows") is True else None),
    )
    comparisons = []
    if all(item["exists"] for item in objects):
        for index, item in enumerate(objects):
            comparison = compare_table_layouts(item["columns"], desired)
            expected_pk = list(desired_pk_columns) if index == 1 else []
            current_pk = list(item.get("primary_key", []))
            comparison["primary_key_before"] = current_pk
            comparison["primary_key_after"] = expected_pk
            comparison["primary_key_changed"] = current_pk != expected_pk
            if comparison["primary_key_changed"]:
                comparison["changed"] = True
                comparison["requires_rebuild"] = True
                comparison["alter_compatible"] = False
            comparisons.append({"schema": item["schema"], "table": item["table"],
                "comparison": comparison, "safe_to_rebuild": item["safe_to_rebuild"], "dependencies": item["dependencies"]})
    changed = any(item["comparison"]["changed"] for item in comparisons)
    blockers = list(physical.get("blocking_reasons", []))
    status = state["status"]
    route = state["route"]
    if route == "APPLY_EMPTY" and not changed:
        status, route = "NO_CHANGE", "NO_CHANGE"
    elif route == "APPLY_EMPTY" and any(item["comparison"]["requires_rebuild"] and not item["safe_to_rebuild"] for item in comparisons):
        status, route = "BLOCKED", "BLOCKED"
        blockers.append("목표 레이아웃 적용에 재생성이 필요하지만 종속 객체가 있어 안전한 교체가 불가합니다.")
    if blockers and route not in {"CREATE_NEW", "TOBE_REQUIRED"}:
        status, route = "BLOCKED", "BLOCKED"
    return {"status": status, "route": route, "reason": state["reason"], "initial_load_required": state["initial_load_required"],
            "identity": identity, "strategy": strategy, "st": st, "l0": l0, "desired_columns": desired,
            "comparisons": comparisons, "blocking_reasons": blockers, "physical": physical,
            "changed": changed, "needs_migration": changed}


def build_layout_work_status(*, metadata_status: str, metadata_message: str | None, migration: dict[str, Any] | None) -> dict[str, Any]:
    """Keep metadata application, physical migration, and load resume state distinct."""
    migration = migration or {}
    route = migration.get("route")
    if route == "APPLY_EMPTY":
        physical_status = "APPLY_EMPTY"
        next_action = "APPLY_EMPTY"
    elif route == "TOBE_REQUIRED":
        physical_status = "TO_BE_REQUIRED"
        next_action = "TOBE_REQUIRED"
    elif route == "CREATE_NEW":
        physical_status = "CREATE_REQUIRED"
        next_action = "CREATE_NEW"
    elif route == "NO_CHANGE":
        physical_status = "CURRENT"
        next_action = "RECHECK_LOAD"
    elif route == "BLOCKED" or migration.get("status") in {"BLOCKED", "UNKNOWN", "UNAVAILABLE"}:
        physical_status = "BLOCKED"
        next_action = "RECHECK"
    else:
        physical_status = "PENDING"
        next_action = "RECHECK"
    return {
        "metadata_status": metadata_status,
        "physical_status": physical_status,
        "load_status": "PAUSED" if metadata_status == "APPLIED" else "NOT_READY",
        "next_action": next_action,
        "message": migration.get("reason") or metadata_message or "메타 변경 후 Datalake 구조 확인이 필요합니다.",
    }


def apply_column_metadata_change(column: Any, after: dict[str, Any], change_type: str, snapshot_id: int | None) -> None:
    """Apply an approved source snapshot to registered metadata, never to Datalake.

    Removal is terminal for this change even if a malformed/stale payload carries
    an ``after`` object; this prevents accidentally reactivating dropped columns.
    """
    if change_type == "COLUMN_REMOVED":
        column.column_status = "INACTIVE"
        column.is_active = "N"
    else:
        if "ordinal_position" in after or "column_id" in after:
            ordinal = after.get("ordinal_position", after.get("column_id"))
            if ordinal is not None:
                column.column_id = int(ordinal)
        if "type" in after and after["type"] is not None:
            column.data_type = str(after["type"])
        for source, target in (("length", "data_length"), ("precision", "data_precision"), ("scale", "data_scale")):
            if source in after:
                setattr(column, target, after[source])
        if "nullable" in after:
            column.null_yn = "N" if after["nullable"] is False else "Y"
        if "comment" in after:
            column.comments = after["comment"]
        column.column_status = "ACTIVE"
        column.is_active = "Y"
    column.column_change_yn = "N"
    column.column_change_type = change_type
    column.metadata_sync_status = "DATALAKE_PENDING"
    column.metadata_sync_message = "메타 반영 완료 · Datalake 물리 구조 반영 대기"
    column.last_layout_snapshot_id = snapshot_id
