"""Persistence and review workflow for registered logical-PK candidates.

The service deliberately keeps source-PK handling before recommendation dispatch.  This is
important both for correctness and because source metadata must never cause an Ollama call.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import re
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import MetaData, Table, and_, desc, insert, select, update
from sqlalchemy.exc import NoSuchTableError

from .collector import source_engine
from .models import DataSource, MetaColumnExt, MetaPkCandidate, MetaTableConfig, MetaTableExt, SchemaSnapshot
from .pk_recommendation import parse_candidate_columns

KEYS = ("system_cd", "instance_name", "postfix", "owner", "table_name")


@contextmanager
def _source_transaction(source):
    resource = source_engine(source)
    if hasattr(resource, "begin"):
        with resource.begin() as connection:
            yield connection
    else:
        with resource as engine:
            with engine.begin() as connection:
                yield connection


@contextmanager
def _source_connection(source):
    resource = source_engine(source)
    if hasattr(resource, "connect"):
        with resource.connect() as connection:
            yield connection
    else:
        with resource as engine:
            with engine.connect() as connection:
                yield connection


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(identity: dict[str, Any], snapshot_id: int | None, columns: list[str]) -> str:
    value = "|".join(str(identity.get(key, "")) for key in KEYS)
    value += f"|{snapshot_id or ''}|{json.dumps(columns, ensure_ascii=False, separators=(',', ':'))}"
    return hashlib.sha256(value.encode()).hexdigest()


def _snapshot_objects(payload: dict[str, Any]) -> dict[tuple[str, str], tuple[str, dict[str, Any], str]]:
    result = {}
    for schema in payload.get("schemas", []):
        schema_name = schema.get("name", "")
        for obj_type, key in (("TABLE", "tables"), ("VIEW", "views")):
            for obj in schema.get(key, []) or []:
                if obj.get("name"):
                    result.setdefault((schema_name, obj["name"]), (schema_name, obj, obj_type))
    return result


def _identity(payload: Any) -> dict[str, Any]:
    return {key: getattr(payload, key) if hasattr(payload, key) else payload.get(key, "") for key in KEYS}


def resolve_registered(session, identity: dict[str, Any]) -> tuple[Any, Any, dict[str, Any], str, Any]:
    """Return (config, registered table, snapshot object, object type, source)."""
    config = session.get(MetaTableConfig, 1)
    if not config:
        raise HTTPException(404, "메타 테이블 조회 설정이 없습니다.")
    source = session.get(DataSource, config.external_source_id) if config.source_type == "external" and config.external_source_id else None
    table = None
    if config.source_type != "external":
        table = session.get(MetaTableExt, tuple(identity[key] for key in KEYS))
        if not table:
            raise HTTPException(404, "등록된 메타 테이블을 찾을 수 없습니다.")
    else:
        if not source:
            raise HTTPException(404, "설정된 외부 DB 접속정보를 찾을 수 없습니다.")
        # External rows are resolved by the same key from the reflected table.
        with _source_connection(source) as connection:
            metadata = MetaData()
            try:
                tables = Table(config.tables_table_name, metadata, schema=config.schema_name, autoload_with=connection)
            except NoSuchTableError as exc:
                raise HTTPException(409, "외부 메타 테이블이 없습니다.") from exc
            cols = {c.name.lower(): c for c in tables.c}
            where = and_(*[cols[key] == identity[key] for key in KEYS])
            row = connection.execute(select(tables).where(where)).mappings().first()
            if not row:
                raise HTTPException(404, "등록된 메타 테이블을 찾을 수 없습니다.")
            table = dict(row)
    snapshot_id = table.src_snapshot_id if hasattr(table, "src_snapshot_id") else table.get("src_snapshot_id")
    snapshot = session.get(SchemaSnapshot, snapshot_id) if snapshot_id else None
    if not snapshot and config.source_type != "external":
        # Legacy/manual registrations may not have source IDs even though the matching
        # object is present in a successful snapshot for the named source.
        source_candidates = session.scalars(select(DataSource).where(DataSource.name == identity["instance_name"])).all()
        for source_candidate in source_candidates:
            snapshots = session.scalars(select(SchemaSnapshot).where(SchemaSnapshot.data_source_id == source_candidate.id).order_by(desc(SchemaSnapshot.captured_at))).all()
            for candidate_snapshot in snapshots:
                candidate_objects = _snapshot_objects(candidate_snapshot.payload)
                found_candidate = candidate_objects.get((identity["owner"], identity["table_name"]))
                if found_candidate:
                    snapshot, source, snapshot_id = candidate_snapshot, source_candidate, candidate_snapshot.id
                    if hasattr(table, "src_data_source_id"):
                        setattr(table, "src_data_source_id", source_candidate.id)
                        setattr(table, "src_snapshot_id", candidate_snapshot.id)
                        session.commit()
                    break
            if snapshot:
                break
    if not snapshot:
        raise HTTPException(404, "등록 메타에 연결된 원천 수집 스냅샷을 찾을 수 없습니다. 원천 연결 또는 수집 이력을 확인해 주세요.")
    objects = _snapshot_objects(snapshot.payload)
    object_name = identity["table_name"]
    found = objects.get((identity["owner"], object_name))
    if not found:
        raise HTTPException(409, "현재 스냅샷에 등록 객체가 없습니다.")
    owner, obj, object_type = found
    if identity["owner"] and owner != identity["owner"]:
        raise HTTPException(409, "등록 메타와 현재 스냅샷의 객체 소유자가 다릅니다.")
    return config, table, obj, object_type, source


def _source_pk(obj: dict[str, Any]) -> list[str]:
    return list((obj.get("primary_key") or {}).get("constrained_columns") or [])


def _match_source_pk_columns(registered_columns: list[str], source_pk: list[str]) -> list[str]:
    """Map source PK names to registered spellings, preferring exact matches."""
    matched = []
    for source_name in source_pk:
        exact = [name for name in registered_columns if name == source_name]
        candidates = exact or [name for name in registered_columns if name.casefold() == source_name.casefold()]
        if not candidates:
            raise HTTPException(409, f"원천 PK 컬럼 '{source_name}'을 등록 메타에서 찾을 수 없습니다. 컬럼 메타를 새로고침해 주세요.")
        if len(candidates) > 1:
            raise HTTPException(409, f"원천 PK 컬럼 '{source_name}'이 여러 등록 컬럼과 일치합니다. 컬럼 메타를 확인해 주세요.")
        matched.append(candidates[0])
    if len(set(matched)) != len(matched):
        raise HTTPException(409, "원천 PK 컬럼이 등록 메타에서 중복 매핑됩니다. 컬럼 메타를 확인해 주세요.")
    return matched


def _column_names(obj: dict[str, Any]) -> set[str]:
    return {str(c.get("name")) for c in obj.get("columns", []) if c.get("name")}


def _candidate_dict(item: Any) -> dict[str, Any]:
    value = item if isinstance(item, dict) else {key: getattr(item, key, None) for key in (
        "candidate_id", "candidate_rank", "candidate_columns_json", "source_type", "method",
        "model_name", "confidence", "reason", "status", "validation_status", "row_count",
        "null_count", "duplicate_group_count", "validation_message", "src_snapshot_id")}
    def get_value(name, default=None):
        if name in value:
            return value[name]
        return next((item for key, item in value.items() if str(key).lower() == name.lower()), default)
    columns = json.loads(get_value("candidate_columns_json") or "[]")
    return {"candidate_id": get_value("candidate_id"), "rank": get_value("candidate_rank"), "columns": columns,
            "source_type": get_value("source_type"), "method": get_value("method"), "model_name": get_value("model_name"),
            "confidence": float(get_value("confidence") or 0), "reason": get_value("reason"), "status": get_value("status"),
            "validation_status": get_value("validation_status"), "row_count": get_value("row_count"), "null_count": get_value("null_count"),
            "duplicate_group_count": get_value("duplicate_group_count"), "validation_message": get_value("validation_message"),
            "src_snapshot_id": get_value("src_snapshot_id")}


def _external_tables(source, config, connection):
    metadata = MetaData()
    kwargs = {"schema": config.schema_name} if config.schema_name else {}
    return (
        Table(config.tables_table_name, metadata, autoload_with=connection, **kwargs),
        Table(config.columns_table_name, metadata, autoload_with=connection, **kwargs),
        Table("TB_META_PK_CANDIDATES_EXT", metadata, autoload_with=connection, **kwargs),
    )


def _row_value(row, name, default=None):
    for key, value in row.items():
        if str(key).lower() == name.lower():
            return value
    return default


def _external_candidate(session, candidate_id):
    config = session.get(MetaTableConfig, 1)
    if not config or config.source_type != "external" or not config.external_source_id:
        return None
    source = session.get(DataSource, config.external_source_id)
    if not source:
        return None
    with _source_connection(source) as connection:
        _, _, candidates = _external_tables(source, config, connection)
        candidate_cols = {str(c.name).lower(): c for c in candidates.c}
        row = connection.execute(select(candidates).where(candidate_cols["candidate_id"] == candidate_id)).mappings().first()
        return (config, source, row)


def _external_config_source(session):
    config = session.get(MetaTableConfig, 1)
    if not config or config.source_type != "external" or not config.external_source_id:
        return None
    source = session.get(DataSource, config.external_source_id)
    return (config, source) if source else None


def update_external_validation(session, candidate_id: int, result: dict[str, Any]) -> None:
    external = _external_candidate(session, candidate_id)
    if not external or not external[2]:
        return
    config, source, _ = external
    with _source_transaction(source) as connection:
        _, _, candidates = _external_tables(source, config, connection)
        cols = {str(c.name).lower(): c for c in candidates.c}
        connection.execute(update(candidates).where(cols["candidate_id"] == candidate_id).values({
            cols["validation_status"]: result["validation_status"],
            cols["status"]: "VALIDATED" if result["validation_status"] == "PASSED" else "GENERATED",
            cols["row_count"]: result.get("row_count"), cols["null_count"]: result.get("null_count"),
            cols["duplicate_group_count"]: result.get("duplicate_group_count"),
            cols["validation_message"]: result.get("message", ""), cols["validated_at"]: _now(),
        }))


def _external_generate(session, config, source, identity, registered, obj, object_type, result, candidates, actor, snapshot_id):
    with _source_transaction(source) as connection:
        tables, _, candidate_table = _external_tables(source, config, connection)
        table_cols = {str(c.name).lower(): c for c in candidate_table.c}
        where = and_(*[table_cols[key] == identity[key] for key in KEYS])
        connection.execute(update(candidate_table).where(where, table_cols["src_snapshot_id"] != snapshot_id,
            table_cols["status"].in_(["GENERATED", "VALIDATED"])).values(STATUS="STALE"))
        persisted = []
        for rank, raw in enumerate(candidates[:4], 1):
            columns = list(raw.get("columns") or [])
            if not columns or len(columns) > 6 or any(c not in _column_names(obj) for c in columns) or len(set(columns)) != len(columns):
                continue
            fp = _fingerprint(identity, snapshot_id, columns)
            existing = connection.execute(select(candidate_table).where(table_cols["candidate_fingerprint"] == fp)).mappings().first()
            values = {"SYSTEM_CD": identity["system_cd"], "INSTANCE_NAME": identity["instance_name"], "POSTFIX": identity["postfix"], "OWNER": identity["owner"], "TABLE_NAME": identity["table_name"], "OBJECT_TYPE": object_type, "SRC_DATA_SOURCE_ID": getattr(registered, "src_data_source_id", None) if hasattr(registered, "src_data_source_id") else registered.get("SRC_DATA_SOURCE_ID"), "SRC_SNAPSHOT_ID": snapshot_id, "CANDIDATE_RANK": rank, "CANDIDATE_COLUMNS_JSON": json.dumps(columns, ensure_ascii=False), "CANDIDATE_FINGERPRINT": fp, "SOURCE_TYPE": raw.get("source_type", result.get("source_type", "OFFLINE_RULES")), "METHOD": raw.get("method", result.get("method", "offline-rules")), "MODEL_NAME": raw.get("model_name"), "CONFIDENCE": min(float(raw.get("confidence", 0)), .75), "REASON": raw.get("reason"), "STATUS": "GENERATED", "VALIDATION_STATUS": "PENDING", "CREATED_BY": actor, "CREATED_AT": _now()}
            if existing:
                connection.execute(update(candidate_table).where(table_cols["candidate_id"] == _row_value(existing, "candidate_id")).values(CANDIDATE_RANK=rank, REASON=values["REASON"]))
                values.update({key: _row_value(existing, key) for key in ("candidate_id", "status", "validation_status", "row_count", "null_count", "duplicate_group_count", "validation_message", "src_snapshot_id")})
                persisted.append(_candidate_dict(values))
            else:
                row = connection.execute(insert(candidate_table).values(**values).returning(table_cols["candidate_id"])).first()
                values["candidate_id"] = row[0] if row else None
                persisted.append(_candidate_dict(values))
    return {"source_pk_applied": False, "candidates": persisted, "fallback_used": bool(result.get("fallback_used", False))}


def _internal_candidates(session, identity: dict[str, Any], snapshot_id: int | None):
    return session.scalars(select(MetaPkCandidate).where(and_(*[getattr(MetaPkCandidate, key) == identity[key] for key in KEYS], MetaPkCandidate.src_snapshot_id == snapshot_id)).order_by(MetaPkCandidate.candidate_rank, MetaPkCandidate.candidate_id)).all()


def generate(session, payload: Any, actor: str, recommender) -> dict[str, Any]:
    identity = _identity(payload)
    config, registered, obj, object_type, source = resolve_registered(session, identity)
    snapshot_id = registered.src_snapshot_id if hasattr(registered, "src_snapshot_id") else registered.get("src_snapshot_id")
    source_pk = _source_pk(obj)
    # Physical PK is authoritative.  Synchronization and response happen without recommender.
    if source_pk:
        if config.source_type != "external":
            registered_columns = session.scalars(select(MetaColumnExt.column_name).filter_by(**identity)).all()
            mapped_source_pk = _match_source_pk_columns(registered_columns, source_pk)
            session.query(MetaColumnExt).filter_by(**identity).update({MetaColumnExt.pk_yn: "N"}, synchronize_session=False)
            session.query(MetaColumnExt).filter_by(**identity).filter(MetaColumnExt.column_name.in_(mapped_source_pk)).update({MetaColumnExt.pk_yn: "Y"}, synchronize_session=False)
            verified_source_pk = session.scalars(select(MetaColumnExt.column_name).filter_by(**identity).where(MetaColumnExt.pk_yn == "Y", MetaColumnExt.column_name.in_(mapped_source_pk))).all()
            if set(verified_source_pk) != set(mapped_source_pk):
                session.rollback()
                raise HTTPException(409, "원천 PK가 등록 메타에 모두 반영되지 않았습니다. 컬럼 메타를 새로고침해 주세요.")
            session.commit()
        else:
            with source_engine(source).begin() as connection:
                _, columns_table, _ = _external_tables(source, config, connection)
                columns = {str(c.name).lower(): c for c in columns_table.c}
                where = and_(*[columns[key] == identity[key] for key in KEYS])
                registered_columns = connection.execute(select(columns["column_name"]).where(where)).scalars().all()
                mapped_source_pk = _match_source_pk_columns(registered_columns, source_pk)
                connection.execute(update(columns_table).where(where).values({columns["pk_yn"]: "N"}))
                connection.execute(update(columns_table).where(and_(where, columns["column_name"].in_(mapped_source_pk))).values({columns["pk_yn"]: "Y"}))
                verified_source_pk = connection.execute(select(columns["column_name"]).where(and_(where, columns["pk_yn"] == "Y", columns["column_name"].in_(mapped_source_pk)))).scalars().all()
                if set(verified_source_pk) != set(mapped_source_pk):
                    raise HTTPException(409, "원천 PK가 등록 메타에 모두 반영되지 않았습니다. 컬럼 메타를 새로고침해 주세요.")
        return {"source_pk_applied": True, "source_pk_columns": source_pk, "candidates": [], "message": "원천 PK가 있어 그대로 적용했습니다."}
    provider = config.description_ai_provider if getattr(config, "description_ai_enabled", False) else "rules"
    result = recommender({**obj, "object_type": object_type}, provider, getattr(config, "description_ai_model", "qwen3:latest"))
    candidates = result.get("candidates", []) if isinstance(result, dict) else []
    if config.source_type == "external":
        return _external_generate(session, config, source, identity, registered, obj, object_type, result, candidates, actor, snapshot_id)
    # Old snapshots are no longer actionable.
    session.query(MetaPkCandidate).filter(*[getattr(MetaPkCandidate, key) == identity[key] for key in KEYS], MetaPkCandidate.src_snapshot_id != snapshot_id, MetaPkCandidate.status.in_(["GENERATED", "VALIDATED"])).update({MetaPkCandidate.status: "STALE"}, synchronize_session=False)
    seen = []
    for rank, raw in enumerate(candidates[:4], 1):
        columns = list(raw.get("columns") or [])
        if not columns or len(columns) > 6 or any(c not in _column_names(obj) for c in columns) or len(set(columns)) != len(columns):
            continue
        fp = _fingerprint(identity, snapshot_id, columns)
        item = session.scalar(select(MetaPkCandidate).where(MetaPkCandidate.candidate_fingerprint == fp))
        if item is None:
            item = MetaPkCandidate(**identity, object_type=object_type, src_data_source_id=getattr(registered, "src_data_source_id", None), src_snapshot_id=snapshot_id, candidate_rank=rank, candidate_columns_json=json.dumps(columns, ensure_ascii=False), candidate_fingerprint=fp, source_type=raw.get("source_type", result.get("source_type", "OFFLINE_RULES")), method=raw.get("method", result.get("method", "offline-rules")), model_name=raw.get("model_name"), confidence=min(float(raw.get("confidence", .0)), .75), reason=raw.get("reason"), status="GENERATED", validation_status="PENDING", created_by=actor)
            session.add(item)
        else:
            item.candidate_rank, item.reason = rank, raw.get("reason") or item.reason
        seen.append(item)
    session.commit()
    return {"source_pk_applied": False, "candidates": [_candidate_dict(item) for item in seen], "fallback_used": bool(result.get("fallback_used", False))}


def list_candidates(session, payload: Any) -> dict[str, Any]:
    identity = _identity(payload)
    config, registered, obj, _, _ = resolve_registered(session, identity)
    source_pk = _source_pk(obj)
    columns = session.scalars(select(MetaColumnExt).filter_by(**identity).order_by(MetaColumnExt.column_id)).all() if config.source_type != "external" else []
    current = [c.column_name for c in columns if c.pk_yn == "Y"]
    source = "SOURCE_PK" if source_pk else ("LOGICAL_PK" if current else "NONE")
    if config.source_type == "external":
        external = _external_config_source(session)
        if not external:
            raise HTTPException(404, "외부 메타 DB를 찾을 수 없습니다.")
        _, external_source = external
        with source_engine(external_source).connect() as connection:
            _, columns_table, candidates_table = _external_tables(external_source, config, connection)
            ccols = {str(c.name).lower(): c for c in columns_table.c}
            cwhere = and_(*[ccols[key] == identity[key] for key in KEYS])
            rows = connection.execute(select(columns_table).where(cwhere)).mappings().all()
            current = [_row_value(row, "column_name") for row in rows if str(_row_value(row, "pk_yn", "N")).upper() == "Y"]
            candidate_cols = {str(c.name).lower(): c for c in candidates_table.c}
            candidate_where = and_(*[candidate_cols[key] == identity[key] for key in KEYS], candidate_cols["src_snapshot_id"] == getattr(registered, "src_snapshot_id", None))
            candidate_rows = connection.execute(select(candidates_table).where(candidate_where).order_by(candidate_cols["candidate_rank"], candidate_cols["candidate_id"])).mappings().all()
            items = [_candidate_dict(dict(row)) for row in candidate_rows]
        current_source = "SOURCE_PK" if source_pk else ("LOGICAL_PK" if current else "NONE")
        return {"current_pk_columns": current, "current_pk_source": current_source, "source_pk_columns": source_pk, "items": items, "can_generate": not bool(source_pk)}
    return {"current_pk_columns": current, "current_pk_source": source, "source_pk_columns": source_pk, "items": [_candidate_dict(i) for i in _internal_candidates(session, identity, getattr(registered, "src_snapshot_id", None))], "can_generate": not bool(source_pk)}


def apply(session, candidate_id: int, confirm: bool, actor: str) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(400, "confirm=true가 필요합니다.")
    item = session.get(MetaPkCandidate, candidate_id)
    external = None
    if not item:
        external = _external_candidate(session, candidate_id)
        if external and external[2]:
            item = dict(external[2])
    if not item:
        raise HTTPException(404, "PK 후보를 찾을 수 없습니다.")
    def value(key):
        if not isinstance(item, dict):
            return getattr(item, key)
        return item.get(key, next((value for name, value in item.items() if str(name).lower() == key.lower()), None))
    if value("status") == "APPLIED" and value("validation_status") == "PASSED":
        return {"candidate_id": value("candidate_id"), "status": value("status"), "applied_columns": json.loads(value("candidate_columns_json"))}
    if value("validation_status") != "PASSED" or value("status") in {"STALE", "REJECTED"}:
        raise HTTPException(409, "검증을 통과한 최신 후보만 적용할 수 있습니다.")
    identity = {key: value(key) for key in KEYS}
    config, registered, obj, _, source = resolve_registered(session, identity)
    registered_snapshot = getattr(registered, "src_snapshot_id", None) if hasattr(registered, "src_snapshot_id") else next((value for key, value in registered.items() if str(key).lower() == "src_snapshot_id"), None)
    if value("src_snapshot_id") != registered_snapshot:
        raise HTTPException(409, "후보의 스냅샷이 현재 등록 메타와 다릅니다.")
    chosen = parse_candidate_columns(value("candidate_columns_json"))
    if not chosen or any(c not in _column_names(obj) for c in chosen) or _source_pk(obj):
        raise HTTPException(409, "현재 스냅샷에서 후보 컬럼을 적용할 수 없습니다.")
    now = _now()
    if config.source_type == "external":
        with _source_transaction(source) as connection:
            _, columns_table, candidates_table = _external_tables(source, config, connection)
            ccols = {str(c.name).lower(): c for c in columns_table.c}
            cands = {str(c.name).lower(): c for c in candidates_table.c}
            where = and_(*[ccols[key] == identity[key] for key in KEYS])
            active_rows = connection.execute(select(columns_table).where(where)).mappings().all()
            active = [row for row in active_rows if str(_row_value(row, "is_active", "Y")).upper() == "Y" and str(_row_value(row, "column_status", "ACTIVE")).upper() == "ACTIVE"]
            if any(column not in {_row_value(row, "column_name") for row in active} for column in chosen):
                raise HTTPException(409, "후보 컬럼이 비활성 상태입니다.")
            connection.execute(update(columns_table).where(where).values({ccols["pk_yn"]: "N"}))
            connection.execute(update(columns_table).where(and_(where, ccols["column_name"].in_(chosen))).values({ccols["pk_yn"]: "Y"}))
            connection.execute(update(candidates_table).where(cands["candidate_id"] == value("candidate_id")).values({cands["status"]: "APPLIED", cands["applied_by"]: actor, cands["applied_at"]: now}))
            connection.execute(update(candidates_table).where(and_(*[cands[key] == identity[key] for key in KEYS], cands["candidate_id"] != value("candidate_id"), cands["status"].in_(["GENERATED", "VALIDATED"]))).values({cands["status"]: "REJECTED", cands["reviewed_by"]: actor, cands["reviewed_at"]: now}))
        return {"candidate_id": value("candidate_id"), "status": "APPLIED", "applied_columns": chosen}
    cols = session.scalars(select(MetaColumnExt).filter_by(**identity)).all()
    active = [c for c in cols if str(c.is_active or "Y").upper() == "Y" and str(c.column_status or "ACTIVE").upper() == "ACTIVE"]
    if any(column not in {x.column_name for x in active} for column in chosen):
        raise HTTPException(409, "후보 컬럼이 비활성 상태입니다.")
    for col in active:
        col.pk_yn = "Y" if col.column_name in chosen else "N"
    item.status, item.applied_by, item.applied_at = "APPLIED", actor, now
    session.query(MetaPkCandidate).filter(*[getattr(MetaPkCandidate, key) == identity[key] for key in KEYS], MetaPkCandidate.candidate_id != value("candidate_id"), MetaPkCandidate.status.in_(["GENERATED", "VALIDATED"])).update({MetaPkCandidate.status: "REJECTED", MetaPkCandidate.reviewed_by: actor, MetaPkCandidate.reviewed_at: now}, synchronize_session=False)
    session.commit()
    return {"candidate_id": value("candidate_id"), "status": item.status, "applied_columns": chosen}


def reject(session, candidate_id: int, reason: str, actor: str) -> dict[str, Any]:
    item = session.get(MetaPkCandidate, candidate_id)
    external = _external_candidate(session, candidate_id) if not item else None
    if external and external[2]:
        config, source, _ = external
        with _source_transaction(source) as connection:
            _, _, candidates = _external_tables(source, config, connection)
            cols = {str(c.name).lower(): c for c in candidates.c}
            connection.execute(update(candidates).where(cols["candidate_id"] == candidate_id).values({cols["status"]: "REJECTED", cols["reviewed_by"]: actor, cols["reviewed_at"]: _now(), cols["validation_message"]: reason[:2000]}))
        return {"candidate_id": candidate_id, "status": "REJECTED", "reason": reason[:2000]}
    if not item:
        raise HTTPException(404, "PK 후보를 찾을 수 없습니다.")
    item.status, item.reviewed_by, item.reviewed_at, item.validation_message = "REJECTED", actor, _now(), reason[:2000]
    session.commit()
    return {"candidate_id": getattr(item, "candidate_id", None), "status": getattr(item, "status", None), "reason": reason[:2000]}
