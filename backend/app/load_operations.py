from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LoadPlanInput:
    system_cd: str
    instance_name: str
    postfix: str
    owner: str
    table_name: str
    table_type: str = "TABLE"
    load_mode: str = "INIT"
    split_strategy: str = "SINGLE"
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    target_chunk_rows: int = 1_000_000
    max_parallelism: int = 1
    source_pool: str | None = None
    allowed_window: str | None = None
    source_watermark: str | None = None


def normalize_plan_input(payload: dict[str, Any]) -> LoadPlanInput:
    strategy = str(payload.get("split_strategy") or "SINGLE").upper()
    if strategy not in {"SINGLE", "SOURCE_PARTITION", "DATE_RANGE", "PK_RANGE", "COMPOSITE"}:
        raise ValueError("지원하지 않는 분할 방식입니다.")
    mode = str(payload.get("load_mode") or "INIT").upper()
    if mode not in {"INIT", "INCREMENTAL"}:
        raise ValueError("적재 방식은 INIT 또는 INCREMENTAL이어야 합니다.")
    rows = payload.get("estimated_rows")
    bytes_ = payload.get("estimated_bytes")
    chunk_rows = 1_000_000 if payload.get("target_chunk_rows") is None else int(payload["target_chunk_rows"])
    parallel = 1 if payload.get("max_parallelism") is None else int(payload["max_parallelism"])
    if rows is not None and int(rows) < 0:
        raise ValueError("예상 행 수는 0 이상이어야 합니다.")
    if bytes_ is not None and int(bytes_) < 0:
        raise ValueError("예상 용량은 0 이상이어야 합니다.")
    if chunk_rows < 1 or chunk_rows > 100_000_000:
        raise ValueError("Chunk 목표 행 수는 1~100,000,000 범위여야 합니다.")
    if parallel < 1 or parallel > 32:
        raise ValueError("최대 병렬도는 1~32 범위여야 합니다.")
    return LoadPlanInput(
        system_cd=str(payload["system_cd"]), instance_name=str(payload["instance_name"]), postfix=str(payload.get("postfix") or ""),
        owner=str(payload["owner"]), table_name=str(payload["table_name"]), table_type=str(payload.get("table_type") or "TABLE"),
        load_mode=mode, split_strategy=strategy, estimated_rows=None if rows is None else int(rows),
        estimated_bytes=None if bytes_ is None else int(bytes_), target_chunk_rows=chunk_rows, max_parallelism=parallel,
        source_pool=(str(payload["source_pool"]).strip() or None) if payload.get("source_pool") is not None else None,
        allowed_window=(str(payload["allowed_window"]).strip() or None) if payload.get("allowed_window") is not None else None,
        source_watermark=(str(payload["source_watermark"]).strip() or None) if payload.get("source_watermark") is not None else None,
    )


def plan_fingerprint(plan: LoadPlanInput) -> str:
    raw = json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_chunks(plan: LoadPlanInput) -> list[dict[str, Any]]:
    rows = plan.estimated_rows
    total_rows = rows or 0
    count = 1 if not rows else max(1, math.ceil(rows / plan.target_chunk_rows))
    expected = None if rows is None else math.ceil(rows / count)
    return [{
        "chunk_no": index,
        "range_start": None,
        "range_end": None,
        "expected_rows": None if expected is None else max(0, min(expected, total_rows - expected * (index - 1))),
        "status": "PENDING",
    } for index in range(1, count + 1)]


def recommend_load_design(columns: list[dict[str, Any]], estimated_rows: int | None, estimated_bytes: int | None, date_recommendation: dict[str, Any]) -> dict[str, Any]:
    names = {str(column.get("column_name", column.get("name", ""))) for column in columns}
    partition = [name for name in date_recommendation.get("partition_columns", []) if name in names][:1]
    update = [name for name in date_recommendation.get("update_base_columns", []) if name in names]
    pk = [str(column.get("column_name", "")) for column in columns if str(column.get("pk_yn", "")).upper() == "Y"]
    if partition and pk and estimated_rows and estimated_rows >= 5_000_000:
        strategy, reason = "COMPOSITE", "생성일자 계열과 PK가 모두 있고 대용량 테이블이므로 날짜·PK 복합 분할을 추천합니다."
    elif partition and estimated_rows and estimated_rows >= 1_000_000:
        strategy, reason = "DATE_RANGE", "생성일자 계열이 확인되고 예상 행 수가 많아 날짜 범위 분할을 추천합니다."
    elif pk and estimated_rows and estimated_rows >= 1_000_000:
        strategy, reason = "PK_RANGE", "PK가 확인되고 예상 행 수가 많아 PK 범위 분할을 추천합니다."
    else:
        strategy, reason = "SINGLE", "분할에 필요한 규모 또는 안정적인 분할 컬럼 정보가 부족해 단일 적재를 추천합니다."
    if estimated_rows and estimated_rows >= 50_000_000:
        chunk_rows, parallel = 1_000_000, 4
    elif estimated_rows and estimated_rows >= 5_000_000:
        chunk_rows, parallel = 1_000_000, 3
    elif estimated_rows and estimated_rows >= 1_000_000:
        chunk_rows, parallel = 500_000, 2
    else:
        chunk_rows, parallel = 1_000_000, 1
    if estimated_bytes and estimated_rows and estimated_bytes / max(estimated_rows, 1) > 4096:
        chunk_rows = min(chunk_rows, 250_000)
        reason += " 행당 데이터가 커 Chunk 목표 행 수를 줄였습니다."
    return {"load_mode": "INCREMENTAL" if update else "INIT", "split_strategy": strategy, "target_chunk_rows": chunk_rows, "max_parallelism": parallel, "partition_columns": partition, "update_base_columns": update, "pk_columns": pk, "confidence": 0.86 if strategy != "SINGLE" else 0.62, "method": "rules", "reason": reason}


def build_manifest(plan: LoadPlanInput, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    key = f"{plan.system_cd}_{plan.owner}_{plan.table_name}".upper().replace("-", "_").replace(".", "_")
    return {
        "schema_version": "1.0",
        "dag_id": f"MV_{plan.load_mode}_{key}",
        "load_mode": plan.load_mode,
        "schedule": "manual" if plan.load_mode == "INIT" else "0 2 * * *",
        "catchup": False,
        "max_active_runs": 1,
        "pool": plan.source_pool,
        "max_parallelism": plan.max_parallelism,
        "split_strategy": plan.split_strategy,
        "plan_fingerprint": plan_fingerprint(plan),
        "tasks": ["check_source", "prepare_staging", "load_chunks", "validate_staging", "publish_l0", "validate_consistency"] if plan.load_mode == "INIT" else ["check_source", "read_watermark", "load_incremental", "publish_l0", "save_watermark"],
        "chunks": chunks,
        "incremental_activation": "after_initial_validation" if plan.load_mode == "INIT" else None,
    }
