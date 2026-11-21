"""Canonical ST/L0 table specification and PostgreSQL DDL renderer."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    data_type: str
    nullable: bool = True


@dataclass(frozen=True)
class TableSpec:
    system_code: str
    source_owner: str
    source_table: str
    st_schema: str
    l0_schema: str
    st_table: str
    l0_table: str
    procedure_name: str
    columns: tuple[ColumnSpec, ...]
    pk_columns: tuple[str, ...]
    update_base_columns: tuple[str, ...]
    partition_column: str | None
    strategy: str
    blocking_reasons: tuple[str, ...] = ()


def _identifier(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value.upper()


def _quote(value: str) -> str:
    return '"' + _identifier(value, "identifier") + '"'


def _qualified(schema: str, table: str) -> str:
    return f"{_quote(schema)}.{_quote(table)}"


def _type(value: Any) -> str:
    raw = str(value or "TEXT").strip().upper()
    raw = re.sub(r"\s+COLLATE\s+.*$", "", raw).strip()
    if raw.startswith(("NUMBER", "DECIMAL", "NUMERIC")):
        return raw.replace("NUMBER", "NUMERIC", 1)
    if raw.startswith(("VARCHAR2", "NVARCHAR2")):
        return raw.replace("VARCHAR2", "VARCHAR", 1).replace("NVARCHAR2", "VARCHAR", 1)
    if raw.startswith(("INT", "INTEGER", "BIGINT", "SMALLINT")):
        return "BIGINT" if raw.startswith("BIGINT") else "INTEGER"
    if raw.startswith(("TIMESTAMP", "DATETIME")):
        return "TIMESTAMPTZ" if "TIME ZONE" in raw else "TIMESTAMP"
    if raw.startswith("DATE"):
        return "DATE"
    if raw.startswith(("FLOAT", "DOUBLE", "REAL")):
        return "DOUBLE PRECISION"
    if raw.startswith(("BOOL", "BOOLEAN")):
        return "BOOLEAN"
    if raw.startswith(("BYTEA", "BLOB", "RAW")):
        return "BYTEA"
    if raw.startswith(("TEXT", "CLOB", "LONGVARCHAR")):
        return "TEXT"
    return raw if re.fullmatch(r"[A-Z][A-Z0-9_]*(\s*\([0-9, ]+\))?", raw) else "TEXT"


def _yes(column: Mapping[str, Any], key: str) -> bool:
    return str(column.get(key, "")).upper() in {"Y", "YES", "TRUE", "1"}


def build_table_spec(metadata: Mapping[str, Any]) -> TableSpec:
    system = _identifier(metadata.get("system_cd"), "system code")
    owner = _identifier(metadata.get("owner"), "owner")
    source_table = _identifier(metadata.get("table_name"), "table")
    st_schema = _identifier(metadata.get("tgt_ds_cd") or f"ST_{system}", "ST schema")
    l0_schema = _identifier(metadata.get("l0_ds_cd") or f"L0_{system}", "L0 schema")
    st_table = _identifier(metadata.get("tgt_table_name") or source_table, "ST table")
    l0_table = _identifier(metadata.get("l0_table_name") or st_table, "L0 table")
    procedure = _identifier(metadata.get("procedure_name") or f"SP_MRG_{l0_table}", "procedure")

    raw_columns: Sequence[Mapping[str, Any]] = metadata.get("columns") or ()
    columns = tuple(
        ColumnSpec(
            name=_identifier(column.get("column_name") or column.get("name"), "column"),
            data_type=_type(column.get("data_type") or column.get("type")),
            nullable=not (_yes(column, "null_yn") is False and str(column.get("null_yn", "")).strip()),
        )
        for column in raw_columns
    )
    if not columns:
        raise ValueError("at least one source column is required")
    names = [column.name for column in columns]
    if len(names) != len(set(names)):
        raise ValueError("duplicate source column names are not allowed")

    pk = tuple(name for name, column in zip(names, raw_columns) if _yes(column, "pk_yn"))
    updates = tuple(name for name, column in zip(names, raw_columns) if _yes(column, "update_base_yn"))
    partitions = [name for name, column in zip(names, raw_columns) if _yes(column, "partition_key_yn")]
    if len(partitions) > 1:
        raise ValueError("only one partition key is supported")
    partition = partitions[0] if partitions else None
    reasons: list[str] = []
    if not pk:
        reasons.append("검증 완료 PK가 없습니다")
    if not updates and not partition:
        reasons.append("UPDATE BASE 또는 날짜 파티션 키가 없습니다")
    strategy = "MERGE" if pk and updates else "PERIOD_REPLACE" if partition else "TRUNCATE_INSERT"
    procedure = {"MERGE": f"SP_MRG_{l0_table}", "PERIOD_REPLACE": f"SP_DEL_INS_{l0_table}", "TRUNCATE_INSERT": f"SP_TRUNC_INS_{l0_table}"}[strategy]
    return TableSpec(system, owner, source_table, st_schema, l0_schema, st_table, l0_table, procedure, columns, pk, updates, partition, strategy, tuple(reasons))


def _standard_columns() -> tuple[ColumnSpec, ...]:
    return (
        ColumnSpec("P_PTT", "DATE", True),
        ColumnSpec("ETL_LOAD_TS", "TIMESTAMPTZ", False),
        ColumnSpec("BATCH_ID", "TEXT", False),
    )


def _columns(spec: TableSpec) -> tuple[ColumnSpec, ...]:
    return spec.columns + _standard_columns()


def _column_definitions(spec: TableSpec) -> str:
    return ",\n  ".join(f"{_quote(column.name)} {column.data_type}{' NOT NULL' if not column.nullable else ''}" for column in _columns(spec))


def _source_select(spec: TableSpec, mode: str | None = None) -> str:
    source = _qualified(spec.st_schema, spec.st_table)
    columns = ", ".join(_quote(column.name) for column in _columns(spec))
    predicates = [f"{_quote('ETL_LOAD_TS')} >= p_window_start", f"{_quote('ETL_LOAD_TS')} < p_window_end", "(p_batch_id IS NULL OR \"BATCH_ID\" = p_batch_id)"]
    effective_mode = mode or spec.strategy
    order = ", ".join([_quote(column) for column in spec.pk_columns] + [f"{_quote(column)} DESC NULLS LAST" for column in spec.update_base_columns])
    if effective_mode == "MERGE":
        return f"SELECT DISTINCT ON ({', '.join(_quote(column) for column in spec.pk_columns)}) {columns} FROM {source} WHERE {' AND '.join(predicates)} ORDER BY {order}"
    return f"SELECT {columns} FROM {source} WHERE {' AND '.join(predicates)}"


def _render_procedure(spec: TableSpec, mode: str) -> str:
    all_columns = _columns(spec)
    names = ", ".join(_quote(column.name) for column in all_columns)
    source = _qualified(spec.st_schema, spec.st_table)
    target = _qualified(spec.l0_schema, spec.l0_table)
    conflict = ", ".join(_quote(column) for column in spec.pk_columns)
    if mode == "MERGE":
        if not spec.pk_columns or not spec.update_base_columns:
            raise ValueError("MERGE에는 검증 완료 PK와 UPDATE BASE가 필요합니다")
        updates = ", ".join(f"{_quote(column.name)} = EXCLUDED.{_quote(column.name)}" for column in all_columns if column.name not in spec.pk_columns)
        latest = " AND ".join(f"(target.{_quote(column)} IS NULL OR target.{_quote(column)} <= EXCLUDED.{_quote(column)})" for column in spec.update_base_columns)
        load = f"INSERT INTO {target} AS target ({names}) SELECT {names} FROM ({_source_select(spec, mode)}) AS source ON CONFLICT ({conflict}) DO UPDATE SET {updates} WHERE {latest};"
        procedure = f"SP_MRG_{spec.l0_table}"
    elif mode == "DELETE_INSERT":
        if not spec.partition_column:
            raise ValueError("DELETE/INSERT에는 PARTITION KEY가 필요합니다")
        partition = _quote(spec.partition_column)
        load = f"DELETE FROM {target} WHERE {partition} >= p_window_start::date AND {partition} < p_window_end::date; INSERT INTO {target} ({names}) {_source_select(spec, mode)};"
        procedure = f"SP_DEL_INS_{spec.l0_table}"
    elif mode == "TRUNCATE_INSERT":
        load = f"IF p_batch_id IS NULL THEN RAISE EXCEPTION 'TRUNCATE/INSERT requires a full-snapshot batch_id'; END IF; TRUNCATE TABLE {target}; INSERT INTO {target} ({names}) {_source_select(spec, mode)};"
        procedure = f"SP_TRUNC_INS_{spec.l0_table}"
    else:
        raise ValueError(f"unsupported procedure strategy: {mode}")
    return f'''CREATE OR REPLACE PROCEDURE {_qualified(spec.l0_schema, procedure)}(p_window_start timestamptz, p_window_end timestamptz, p_instance text, p_batch_id text)\nLANGUAGE plpgsql\nAS $$\nBEGIN\n  PERFORM p_instance;\n  {load}\nEND;\n$$;\n'''


def render_postgresql_procedure_scripts(spec: TableSpec) -> dict[str, dict[str, Any]]:
    reasons = {
        "MERGE": "검증 완료 PK와 UPDATE BASE가 있어 동일 PK의 최신 변경만 반영하고 재실행 중복을 막을 수 있어 추천합니다.",
        "DELETE_INSERT": "PARTITION KEY 기간을 먼저 삭제한 뒤 다시 적재해 해당 기간을 재생성합니다. 기간 재적재가 필요한 경우 선택합니다.",
        "TRUNCATE_INSERT": "전체 스냅샷을 기준으로 대상 L0를 비우고 다시 적재합니다. 전체 스냅샷이 보장되는 경우에만 선택합니다.",
    }
    available = {
        "MERGE": bool(spec.pk_columns and spec.update_base_columns),
        "DELETE_INSERT": bool(spec.partition_column),
        "TRUNCATE_INSERT": True,
    }
    scripts: dict[str, dict[str, Any]] = {}
    for mode in ("MERGE", "DELETE_INSERT", "TRUNCATE_INSERT"):
        if available[mode]:
            sql_text = _render_procedure(spec, mode)
        else:
            sql_text = None
        scripts[mode] = {
            "strategy": mode,
            "available": available[mode],
            "recommended": spec.strategy == ("PERIOD_REPLACE" if mode == "DELETE_INSERT" else mode),
            "reason": reasons[mode] if available[mode] else reasons[mode] + " 현재 메타에는 필요한 키가 없어 선택할 수 없습니다.",
            "procedure_name": {"MERGE": f"SP_MRG_{spec.l0_table}", "DELETE_INSERT": f"SP_DEL_INS_{spec.l0_table}", "TRUNCATE_INSERT": f"SP_TRUNC_INS_{spec.l0_table}"}[mode],
            "sql": sql_text,
        }
    return scripts


def render_postgresql_ddl(spec: TableSpec, *, include_procedure: bool = True, procedure_strategy: str | None = None) -> str:
    if spec.strategy == "MANUAL_REQUIRED":
        raise ValueError("DDL 생성을 차단했습니다: " + ", ".join(spec.blocking_reasons))
    all_columns = _columns(spec)
    source = _qualified(spec.st_schema, spec.st_table)
    target = _qualified(spec.l0_schema, spec.l0_table)
    conflict = ", ".join(_quote(column) for column in spec.pk_columns)
    target_constraint = f",\n  CONSTRAINT {_quote(f'PK_{spec.l0_table}')} PRIMARY KEY ({conflict})" if spec.pk_columns else ""
    procedure = ""
    if include_procedure:
        mode = "DELETE_INSERT" if (procedure_strategy or spec.strategy) == "PERIOD_REPLACE" else (procedure_strategy or spec.strategy)
        scripts = render_postgresql_procedure_scripts(spec)
        selected = scripts.get(mode)
        if not selected or not selected["available"]:
            raise ValueError(selected["reason"] if selected else f"unsupported procedure strategy: {mode}")
        procedure = selected["sql"]
    return f'''-- MetaVault canonical TableSpec: {spec.system_code}.{spec.source_table}\nCREATE SCHEMA IF NOT EXISTS {_quote(spec.st_schema)};\nCREATE SCHEMA IF NOT EXISTS {_quote(spec.l0_schema)};\n\nCREATE TABLE IF NOT EXISTS {source} (\n  {_column_definitions(spec)}\n);\n\nCREATE TABLE IF NOT EXISTS {target} (\n  {_column_definitions(spec)}{target_constraint}\n);\n\n{procedure}'''
