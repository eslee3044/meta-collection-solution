"""Manual external-AI recommendation prompt and validation for Datalake loads."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

SCHEMA_VERSION = "1.0"
_ALLOWED_RESPONSE_KEYS = {
    "schema_version", "request_id", "identity_fingerprint", "load_mode", "split_strategy",
    "partition_columns", "update_base_columns", "target_chunk_rows", "max_parallelism",
    "confidence", "reason", "risks",
}
_ALLOWED_SPLITS = {"SINGLE", "SOURCE_PARTITION", "DATE_RANGE", "PK_RANGE", "COMPOSITE"}
_DATE_TYPES = ("DATE", "DATETIME", "TIMESTAMP", "TIME")
_CREATED_WORDS = ("CREATED", "CREATE", "CRT", "REGIST", "REGISTERED", "INSERT", "생성", "등록")
_CHANGED_WORDS = ("UPDATED", "UPDATE", "UPDT", "MODIFIED", "CHANGED", "CHANGE", "LAST", "변경", "수정")


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    columns = []
    for raw in list(metadata.get("columns") or [])[:500]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("column_name") or "").strip()
        if not name:
            continue
        columns.append({
            "column_name": name[:255],
            "data_type": str(raw.get("data_type") or "")[:100],
            "nullable": bool(raw.get("nullable")) if isinstance(raw.get("nullable"), bool) else raw.get("nullable"),
            "pk_yn": str(raw.get("pk_yn") or "N")[:1],
            "partition_key_yn": str(raw.get("partition_key_yn") or "N")[:1],
            "update_base_yn": str(raw.get("update_base_yn") or "N")[:1],
        })
    return {
        "table": {
            "system_cd": str(metadata.get("system_cd") or "")[:32],
            "instance_name": str(metadata.get("instance_name") or "")[:255],
            "postfix": str(metadata.get("postfix") or "")[:32],
            "owner": str(metadata.get("owner") or "")[:255],
            "table_name": str(metadata.get("table_name") or "")[:255],
            "db_type": str(metadata.get("db_type") or "")[:30],
        },
        "statistics": {
            "estimated_rows": metadata.get("estimated_rows"),
            "estimated_bytes": metadata.get("estimated_bytes"),
        },
        "runtime_limits": {
            "pool_slots": int(metadata.get("pool_slots") or 1),
            "max_parallelism_allowed": int(metadata.get("max_parallelism_allowed") or 32),
        },
        "columns": columns,
    }


def _fingerprint(metadata: dict[str, Any]) -> str:
    canonical = json.dumps(_safe_metadata(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _request_id(fingerprint: str, secret: str) -> str:
    return "load1_" + hmac.new(secret.encode(), f"load-ai:{SCHEMA_VERSION}:{fingerprint}".encode(), hashlib.sha256).hexdigest()


def build_load_prompt(metadata: dict[str, Any], secret: str) -> dict[str, Any]:
    safe = _safe_metadata(metadata)
    fingerprint = _fingerprint(metadata)
    request_id = _request_id(fingerprint, secret)
    shape = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "identity_fingerprint": fingerprint,
        "load_mode": "INIT or INCREMENTAL",
        "split_strategy": "SINGLE, SOURCE_PARTITION, DATE_RANGE, PK_RANGE, or COMPOSITE",
        "partition_columns": ["CREATED_AT"],
        "update_base_columns": ["UPDATED_AT"],
        "target_chunk_rows": 500000,
        "max_parallelism": 2,
        "confidence": 0.0,
        "reason": "한국어 근거",
        "risks": ["위험 또는 확인 사항"],
    }
    prompt = f"""요청 유형: DATALAKE_LOAD_RECOMMENDATION
당신은 Datalake 적재 설계 추천 도우미입니다.
입력된 메타데이터만 사용하고 실제 데이터나 접속정보를 추측하지 마세요.

규칙:
- 입력 JSON의 컬럼명만 추천하고 존재하지 않는 컬럼을 만들지 마세요.
- PARTITION KEY는 생성일자 계열 중 최대 1개만 추천하세요.
- UPDATE BASE는 변경일자 계열을 우선해 여러 개 추천하고, 없으면 생성일자 계열을 사용하세요.
- 병렬도는 runtime_limits.max_parallelism_allowed를 넘지 마세요.
- 통계가 없으면 confidence를 낮추고 risks에 통계 확인 필요를 작성하세요.
- Markdown, 코드 펜스, 설명 문장 없이 JSON 객체 하나만 반환하세요.
- 아래 응답 구조 외 필드는 추가하지 마세요.

입력 메타데이터:
{json.dumps(safe, ensure_ascii=False, indent=2)}

응답 JSON 구조:
{json.dumps(shape, ensure_ascii=False, indent=2)}"""
    return {"schema_version": SCHEMA_VERSION, "request_id": request_id, "identity_fingerprint": fingerprint, "prompt": prompt}


def _parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw or raw.startswith("```") or raw.endswith("```"):
        raise ValueError("Markdown 코드 펜스 없이 JSON 객체만 붙여넣어 주세요.")
    if len(raw.encode()) > 100_000:
        raise ValueError("AI 응답은 100KB를 넘을 수 없습니다.")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 형식이 올바르지 않습니다: {error.msg} (줄 {error.lineno}, 열 {error.colno})") from error
    if not isinstance(body, dict):
        raise ValueError("AI 응답은 JSON 객체여야 합니다.")
    extras = set(body) - _ALLOWED_RESPONSE_KEYS
    if extras:
        raise ValueError(f"응답에 허용되지 않은 필드가 있습니다: {', '.join(sorted(extras))}")
    return body


def _columns(value: Any, available: dict[str, dict[str, Any]], label: str, maximum: int = 500) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label}은 컬럼명 배열이어야 합니다.")
    values = list(dict.fromkeys(value))
    unknown = [item for item in values if item not in available]
    if unknown:
        raise ValueError(f"존재하지 않는 컬럼이 포함되어 있습니다: {', '.join(unknown)}")
    return values


def _is_date(column_name: str, column: dict[str, Any]) -> bool:
    return any(token in str(column.get("data_type") or "").upper() for token in _DATE_TYPES)


def validate_load_response(response_text: str, metadata: dict[str, Any], secret: str) -> dict[str, Any]:
    body = _parse_json(response_text)
    envelope = build_load_prompt(metadata, secret)
    if body.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 응답 스키마 버전입니다.")
    if not hmac.compare_digest(str(body.get("request_id") or ""), envelope["request_id"]):
        raise ValueError("AI 응답의 요청 식별자가 현재 프롬프트와 일치하지 않습니다.")
    if not hmac.compare_digest(str(body.get("identity_fingerprint") or ""), envelope["identity_fingerprint"]):
        raise ValueError("AI 응답이 현재 테이블 메타와 일치하지 않습니다. 프롬프트를 다시 생성해 주세요.")
    if body.get("load_mode") not in {"INIT", "INCREMENTAL"}:
        raise ValueError("load_mode는 INIT 또는 INCREMENTAL이어야 합니다.")
    if body.get("split_strategy") not in _ALLOWED_SPLITS:
        raise ValueError("허용되지 않은 분할 방식입니다.")
    safe = _safe_metadata(metadata)
    available = {item["column_name"]: item for item in safe["columns"]}
    if len(body.get("partition_columns") or []) > 1:
        raise ValueError("PARTITION KEY는 최대 1개만 추천할 수 있습니다.")
    partition = _columns(body.get("partition_columns"), available, "PARTITION KEY", 1)
    if partition and not _is_date(partition[0], available[partition[0]]):
        raise ValueError("PARTITION KEY는 날짜·시간 타입 컬럼이어야 합니다.")
    update = _columns(body.get("update_base_columns"), available, "UPDATE BASE")
    if any(not _is_date(name, available[name]) for name in update):
        raise ValueError("UPDATE BASE는 날짜·시간 타입 컬럼이어야 합니다.")
    chunk = body.get("target_chunk_rows")
    parallel = body.get("max_parallelism")
    confidence = body.get("confidence")
    if isinstance(chunk, bool) or not isinstance(chunk, int) or not 1 <= chunk <= 100_000_000:
        raise ValueError("target_chunk_rows는 1부터 100,000,000 사이의 정수여야 합니다.")
    if isinstance(parallel, bool) or not isinstance(parallel, int) or not 1 <= parallel <= 32:
        raise ValueError("max_parallelism은 1부터 32 사이의 정수여야 합니다.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence는 0.0부터 1.0 사이의 숫자여야 합니다.")
    if not isinstance(body.get("reason"), str) or not body["reason"].strip() or len(body["reason"]) > 1000:
        raise ValueError("reason은 1,000자 이내의 설명 문자열이어야 합니다.")
    risks = body.get("risks")
    if not isinstance(risks, list) or len(risks) > 20 or any(not isinstance(item, str) or len(item) > 500 for item in risks):
        raise ValueError("risks는 문자열 배열이어야 합니다.")
    pool_slots = safe["runtime_limits"]["pool_slots"]
    max_allowed = safe["runtime_limits"]["max_parallelism_allowed"]
    final_parallel = min(parallel, pool_slots, max_allowed)
    adjustments = []
    if final_parallel != parallel:
        adjustments.append(f"최대 병렬도를 원천 Pool·정책 제한에 맞춰 {parallel}에서 {final_parallel}로 조정했습니다.")
    status = "ADJUSTED" if adjustments else "VALID"
    return {
        "provider": "manual",
        "method": "manual-ai+rules",
        "recommendation": {
            "load_mode": body["load_mode"],
            "split_strategy": body["split_strategy"],
            "partition_columns": partition,
            "update_base_columns": update,
            "target_chunk_rows": chunk,
            "max_parallelism": final_parallel,
            "confidence": float(confidence),
            "reason": body["reason"].strip(),
            "risks": risks,
        },
        "validation": {"status": status, "adjustments": adjustments, "warnings": []},
    }
