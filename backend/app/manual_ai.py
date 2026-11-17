"""Manual AI prompt generation and untrusted response validation.

The manual mode never calls an AI service. It exports an allowlisted metadata
prompt and validates pasted JSON before the UI may stage recommendations.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

_SCHEMA_VERSION = "1.0"
_COLUMN_KEYS = ("column_name", "data_type", "nullable", "null_yn", "pk_yn", "index_yn", "index_names", "ordinal_position")
_CREATED_RE = re.compile(r"(?:CRT|CREATED|CREATE|CREATION|REGIST|REGISTERED|INSERT|입력|등록|생성)", re.I)
_CHANGED_RE = re.compile(r"(?:UPDT|UPDATE|UPDATED|MODIFIED|MODIFY|CHANGED|CHANGE|LAST|변경|수정)", re.I)
_DATE_RE = re.compile(r"(?:DATE|DATETIME|TIMESTAMP|TIME)", re.I)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for raw in list(metadata.get("columns") or [])[:500]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("column_name") or "").strip()
        if not name:
            continue
        column = {key: raw.get(key) for key in _COLUMN_KEYS if raw.get(key) is not None}
        column["column_name"] = name[:255]
        column["data_type"] = str(raw.get("data_type") or "")[:255]
        column["description_target"] = not bool(str(raw.get("comments") or raw.get("description") or "").strip())
        if "index_names" in column:
            column["index_names"] = [str(value)[:255] for value in list(column["index_names"] or [])[:30]]
        columns.append(column)
    return {
        "owner": str(metadata.get("owner") or "")[:255],
        "table_name": str(metadata.get("table_name") or "")[:255],
        "object_type": str(metadata.get("object_type") or "TABLE").upper()[:20],
        "snapshot_id": metadata.get("snapshot_id"),
        "description_target": not bool(str(metadata.get("comments") or "").strip()),
        "columns": columns,
    }


def _canonical(metadata: dict[str, Any]) -> str:
    return json.dumps(_sanitize_metadata(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(metadata: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(metadata).encode()).hexdigest()


def _request_id(fingerprint: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), f"manual-ai:{_SCHEMA_VERSION}:{fingerprint}".encode(), hashlib.sha256).hexdigest()
    return f"mv1_{digest}"


def build_manual_prompt(metadata: dict[str, Any], secret: str) -> dict[str, str]:
    sanitized = _sanitize_metadata(metadata)
    fingerprint = _fingerprint(sanitized)
    request_id = _request_id(fingerprint, secret)
    response_shape = {
        "schema_version": _SCHEMA_VERSION,
        "request_id": request_id,
        "snapshot_fingerprint": fingerprint,
        "recommendations": {
            "table_descriptions": [{"value": "설명", "reason": "근거", "confidence": 0.0}],
            "column_descriptions": [{"column_name": "COLUMN_NAME", "suggestions": [{"value": "설명", "reason": "근거", "confidence": 0.0}]}],
            "pk_candidates": [{"columns": ["COLUMN_NAME"], "reason": "근거", "confidence": 0.0}],
            "partition_key_columns": ["CREATED_AT"],
            "update_base_columns": ["UPDATED_AT"],
        },
    }
    prompt = f"""당신은 데이터 카탈로그 메타데이터 추천 도우미입니다.
제공된 메타데이터만 사용하고, 실제 데이터 값이나 제공되지 않은 업무 정보를 추측하지 마세요.

추천 항목:
1. 테이블 설명 후보 최대 4개
2. 설명이 필요한 컬럼별 설명 후보 최대 4개
3. 논리 PK 후보 최대 4개(확정 PK가 아니라 검증이 필요한 후보)
4. PARTITION KEY: 생성일자 계열 중 최대 1개
5. UPDATE BASE: 변경일자 계열을 우선해 복수 선택하고, 없으면 생성일자 계열 선택

응답 규칙:
- 아래 입력에 존재하는 테이블과 컬럼만 사용하세요.
- schema_version, request_id, snapshot_fingerprint를 아래 값 그대로 반환하세요.
- confidence는 0.0~1.0 숫자입니다.
- reason은 짧고 명확한 한국어로 작성하세요.
- 추천할 수 없는 배열은 빈 배열로 반환하세요.
- SQL, HTML, 스크립트, 설명 문장을 출력하지 마세요.
- Markdown 코드 펜스를 사용하지 말고 단일 JSON 객체만 반환하세요.
- 아래 응답 구조에 없는 필드를 추가하지 마세요.

입력 메타데이터:
{json.dumps(sanitized, ensure_ascii=False, indent=2)}

응답 JSON 구조:
{json.dumps(response_shape, ensure_ascii=False, indent=2)}"""
    return {"schema_version": _SCHEMA_VERSION, "request_id": request_id, "snapshot_fingerprint": fingerprint, "prompt": prompt}


def _strict_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    extras = set(value) - allowed
    if extras:
        raise ValueError(f"{label}에 허용되지 않은 필드가 있습니다: {', '.join(sorted(extras))}")


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError("신뢰도는 0.0부터 1.0 사이의 숫자여야 합니다.")
    return float(value)


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")
    if len(value.strip()) > limit:
        raise ValueError(f"{label}은 {limit}자를 넘을 수 없습니다.")
    return value.strip()


def validate_manual_response(response_text: str, metadata: dict[str, Any], secret: str) -> dict[str, Any]:
    raw = str(response_text or "").strip()
    if raw.startswith("```") or raw.endswith("```"):
        raise ValueError("Markdown 코드 펜스 없이 JSON 객체만 붙여넣어 주세요.")
    if len(raw.encode()) > 200_000:
        raise ValueError("AI 응답은 200KB를 넘을 수 없습니다.")
    try:
        def reject_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"중복된 JSON 필드가 있습니다: {key}")
                result[key] = value
            return result
        decoder = json.JSONDecoder(
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"허용되지 않는 숫자입니다: {value}")),
        )
        body, parsed_end = decoder.raw_decode(raw)
        trailing = raw[parsed_end:].strip()
        normalization_warnings: list[str] = []
        if trailing:
            if len(trailing) <= 2 and set(trailing) == {"}"}:
                normalization_warnings.append(f"응답 끝의 불필요한 닫는 중괄호 {len(trailing)}개를 제거했습니다.")
            else:
                raise json.JSONDecodeError("Extra data", raw, parsed_end)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 형식이 올바르지 않습니다: {error.msg} (줄 {error.lineno}, 열 {error.colno})") from error
    if not isinstance(body, dict):
        raise ValueError("AI 응답은 JSON 객체여야 합니다.")
    _strict_keys(body, {"schema_version", "request_id", "snapshot_fingerprint", "recommendations"}, "최상위 응답")
    envelope = build_manual_prompt(metadata, secret)
    if body.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("지원하지 않는 응답 스키마 버전입니다.")
    if not hmac.compare_digest(str(body.get("request_id") or ""), envelope["request_id"]):
        raise ValueError("AI 응답의 요청 식별자가 현재 프롬프트와 일치하지 않습니다.")
    if not hmac.compare_digest(str(body.get("snapshot_fingerprint") or ""), envelope["snapshot_fingerprint"]):
        raise ValueError("AI 응답이 현재 메타데이터 스냅샷과 일치하지 않습니다. 프롬프트를 다시 생성해 주세요.")
    recommendations = body.get("recommendations")
    if not isinstance(recommendations, dict):
        raise ValueError("recommendations는 JSON 객체여야 합니다.")
    allowed_groups = {"table_descriptions", "column_descriptions", "pk_candidates", "partition_key_columns", "update_base_columns"}
    _strict_keys(recommendations, allowed_groups, "recommendations")
    sanitized = _sanitize_metadata(metadata)
    columns = {column["column_name"]: column for column in sanitized["columns"]}

    def column_names(group: str, maximum: int = 500) -> list[str]:
        values = recommendations.get(group, [])
        if not isinstance(values, list) or len(values) > maximum or any(not isinstance(value, str) for value in values):
            raise ValueError(f"{group}는 최대 {maximum}개의 컬럼명 배열이어야 합니다.")
        unknown = [value for value in values if value not in columns]
        if unknown:
            raise ValueError(f"존재하지 않는 컬럼이 포함되어 있습니다: {', '.join(unknown)}")
        return list(dict.fromkeys(values))

    table_descriptions = recommendations.get("table_descriptions", [])
    if not isinstance(table_descriptions, list) or len(table_descriptions) > 4:
        raise ValueError("테이블 설명 후보는 최대 4개입니다.")
    if table_descriptions and not sanitized.get("description_target", True):
        raise ValueError("테이블에 이미 설명이 있어 가져올 수 없습니다.")
    normalized_tables = []
    for item in table_descriptions:
        if not isinstance(item, dict):
            raise ValueError("테이블 설명 후보 형식이 올바르지 않습니다.")
        _strict_keys(item, {"value", "reason", "confidence"}, "테이블 설명 후보")
        normalized_tables.append({"value": _text(item.get("value"), "테이블 설명", 4000), "reason": _text(item.get("reason"), "추천 근거", 500), "confidence": _confidence(item.get("confidence"))})

    column_descriptions = recommendations.get("column_descriptions", [])
    if not isinstance(column_descriptions, list) or len(column_descriptions) > 500:
        raise ValueError("컬럼 설명 대상은 최대 500개입니다.")
    normalized_columns = []
    seen_columns: set[str] = set()
    for item in column_descriptions:
        if not isinstance(item, dict):
            raise ValueError("컬럼 설명 후보 형식이 올바르지 않습니다.")
        _strict_keys(item, {"column_name", "suggestions"}, "컬럼 설명 대상")
        name = str(item.get("column_name") or "")
        if name not in columns:
            raise ValueError(f"존재하지 않는 컬럼이 포함되어 있습니다: {name}")
        if not columns[name].get("description_target", True):
            raise ValueError(f"이미 설명이 있어 가져올 수 없습니다: {name}")
        if name in seen_columns:
            raise ValueError(f"중복된 컬럼 설명 대상입니다: {name}")
        seen_columns.add(name)
        suggestions = item.get("suggestions", [])
        if not isinstance(suggestions, list) or not 1 <= len(suggestions) <= 4:
            raise ValueError("컬럼 설명 후보는 대상별 1~4개여야 합니다.")
        normalized_suggestions = []
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                raise ValueError("컬럼 설명 제안 형식이 올바르지 않습니다.")
            _strict_keys(suggestion, {"value", "reason", "confidence"}, "컬럼 설명 제안")
            normalized_suggestions.append({"value": _text(suggestion.get("value"), "컬럼 설명", 4000), "reason": _text(suggestion.get("reason"), "추천 근거", 500), "confidence": _confidence(suggestion.get("confidence"))})
        normalized_columns.append({"column_name": name, "suggestions": normalized_suggestions})

    pk_candidates = recommendations.get("pk_candidates", [])
    if not isinstance(pk_candidates, list) or len(pk_candidates) > 4:
        raise ValueError("PK 후보는 최대 4개입니다.")
    normalized_pk = []
    source_pk = [name for name, column in columns.items() if str(column.get("pk_yn") or "").upper() == "Y"]
    if pk_candidates and source_pk:
        normalization_warnings.append(f"현재 PK({', '.join(source_pk)})가 이미 식별되어 AI PK 후보를 모두 제외했습니다.")
        pk_candidates = []
    seen_pk: set[tuple[str, ...]] = set()
    for item in pk_candidates:
        if not isinstance(item, dict):
            raise ValueError("PK 후보 형식이 올바르지 않습니다.")
        _strict_keys(item, {"columns", "reason", "confidence"}, "PK 후보")
        candidate_columns = item.get("columns", [])
        if not isinstance(candidate_columns, list) or not 1 <= len(candidate_columns) <= 6 or any(not isinstance(value, str) for value in candidate_columns):
            raise ValueError("PK 후보 컬럼은 1~6개여야 합니다.")
        unknown = [value for value in candidate_columns if value not in columns]
        if unknown:
            raise ValueError(f"존재하지 않는 컬럼이 포함되어 있습니다: {', '.join(unknown)}")
        if len(set(candidate_columns)) != len(candidate_columns):
            raise ValueError("PK 후보 안에 같은 컬럼을 중복해서 넣을 수 없습니다.")
        nullable = [value for value in candidate_columns if str(columns[value].get("nullable") or columns[value].get("null_yn") or "").upper() in {"TRUE", "Y"}]
        if nullable:
            normalization_warnings.append(f"PK 후보({', '.join(candidate_columns)})를 제외했습니다: NULL 허용 컬럼 {', '.join(nullable)}")
            continue
        signature = tuple(candidate_columns)
        if signature in seen_pk:
            raise ValueError("같은 PK 후보 조합이 중복되었습니다.")
        seen_pk.add(signature)
        normalized_pk.append({"columns": candidate_columns, "reason": _text(item.get("reason"), "추천 근거", 500), "confidence": _confidence(item.get("confidence")), "requires_source_validation": True})

    partition = column_names("partition_key_columns", 1)
    if len(recommendations.get("partition_key_columns", [])) > 1:
        raise ValueError("PARTITION KEY는 최대 1개만 선택할 수 있습니다.")
    if partition:
        column = columns[partition[0]]
        if not (_DATE_RE.search(str(column.get("data_type") or "")) and _CREATED_RE.search(partition[0])):
            normalization_warnings.append(f"PARTITION KEY({partition[0]})를 제외했습니다: 생성일자 계열 컬럼이 아닙니다.")
            partition = []
    update_base = column_names("update_base_columns")
    changed_available = any(_DATE_RE.search(str(column.get("data_type") or "")) and _CHANGED_RE.search(name) for name, column in columns.items())
    valid_update_base = []
    for name in update_base:
        column = columns[name]
        valid_name = _CHANGED_RE.search(name) if changed_available else _CREATED_RE.search(name)
        if not (_DATE_RE.search(str(column.get("data_type") or "")) and valid_name):
            normalization_warnings.append(f"UPDATE BASE({name})를 제외했습니다: 변경일자 우선·생성일자 대체 규칙에 맞지 않습니다.")
            continue
        valid_update_base.append(name)
    update_base = valid_update_base

    return {
        "valid": True,
        "schema_version": _SCHEMA_VERSION,
        "request_id": envelope["request_id"],
        "snapshot_fingerprint": envelope["snapshot_fingerprint"],
        "normalization_warnings": normalization_warnings,
        "recommendations": {
            "table_descriptions": normalized_tables,
            "column_descriptions": normalized_columns,
            "pk_candidates": normalized_pk,
            "partition_key_columns": partition,
            "update_base_columns": update_base,
        },
    }
