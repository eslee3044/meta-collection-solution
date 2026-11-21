"""Offline metadata description suggestions.

This module never accesses source databases or external AI APIs. The optional
Ollama provider is restricted to a locally configured URL and receives only
non-sensitive schema names, column names, and data types.
"""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
_ALLOWED_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _words(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value or "")
    return [part for part in re.split(r"[_\-\s]+", value.upper()) if part]


def rule_description(table_name: str, column_name: str, data_type: str = "") -> tuple[str, float]:
    words = _words(column_name)
    joined = "_".join(words)
    exact = {
        "ID": "식별자",
        "NO": "번호",
        "NAME": "명칭",
        "NM": "명칭",
        "CODE": "코드",
        "CD": "코드",
        "STATUS": "상태",
        "STS": "상태",
        "STATUS_CD": "상태 코드",
        "STS_CD": "상태 코드",
        "Y_N": "여부",
        "YN": "여부",
        "USE_YN": "사용 여부",
        "AMOUNT": "금액",
        "AMT": "금액",
        "COUNT": "건수",
        "CNT": "건수",
        "EMAIL": "이메일 주소",
        "PHONE": "전화번호",
        "TEL": "전화번호",
        "ADDRESS": "주소",
        "ADDR": "주소",
        "DESCRIPTION": "설명",
        "DESC": "설명",
        "CREATED_AT": "생성 일시",
        "CREATE_DT": "생성 일자",
        "CREATED_DT": "생성 일자",
        "UPDATED_AT": "최종 변경 일시",
        "UPDATE_DT": "최종 변경 일자",
        "UPDATED_DT": "최종 변경 일자",
    }
    if joined in exact:
        return exact[joined], 0.99
    if words and words[-1] in {"ID", "KEY"}:
        return f"{' '.join(words[:-1]).title()} 식별자" if len(words) > 1 else "식별자", 0.94
    if words and words[-1] in {"CD", "CODE"}:
        return f"{' '.join(words[:-1]).title()} 코드" if len(words) > 1 else "코드", 0.93
    if words and words[-1] in {"YN", "FLAG", "FLG"}:
        return f"{' '.join(words[:-1]).title()} 여부" if len(words) > 1 else "여부", 0.91
    if any(token in words for token in ("DATE", "DT", "DTE", "TIME", "AT", "DTTM")):
        return f"{column_name} 일시/일자", 0.78
    if any(token in words for token in ("AMOUNT", "AMT", "PRICE", "COST", "FEE")):
        return f"{column_name} 금액", 0.82
    if data_type and any(token in data_type.upper() for token in ("DATE", "TIME", "TIMESTAMP")):
        return f"{column_name} 일시", 0.72
    return f"{column_name} 정보", 0.45


def _candidate_rules(column_name: str, data_type: str = "") -> list[str]:
    primary, _ = rule_description("", column_name, data_type)
    words = _words(column_name)
    base = " ".join(words).title() or column_name
    candidates = [primary]
    if words and words[-1] in {"ID", "KEY"}:
        candidates += [f"{base} 번호", f"{base} 식별값", f"{column_name} ID"]
    elif words and words[-1] in {"YN", "FLAG", "FLG"}:
        candidates += [f"{base} 여부 값", f"{base} 사용 상태", f"{column_name} 플래그"]
    elif words and words[-1] in {"AT", "DT", "DATE", "TIME", "DTTM"}:
        candidates += [f"{base} 일시", f"{base} 발생 시간", f"{column_name} 날짜"]
    else:
        candidates += [f"{base} 설명", f"{base} 값", f"{column_name} 데이터"]
    return list(dict.fromkeys(candidates))[:4]


def _table_candidates(table_name: str, columns: list[dict]) -> list[str]:
    name = str(table_name or "").strip()
    column_names = [str(column.get("column_name", "")).strip() for column in columns if str(column.get("column_name", "")).strip()][:4]
    suffix = f" ({', '.join(column_names)})" if column_names else ""
    return [
        f"{name} 테이블의 데이터를 관리합니다.",
        f"{name} 테이블의 업무 데이터를 저장합니다.",
        f"{name} 테이블은 {', '.join(column_names[:3]) or '주요 업무 정보'}를 관리합니다.",
        f"{name} 테이블의 메타데이터와 처리 대상 정보를 관리합니다{suffix}.",
    ]


def _ollama_suggestions(targets: list[dict], table_name: str, table_columns: list[dict], model: str, base_url: str) -> dict[str, list[str]]:
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in _ALLOWED_LOCAL_HOSTS:
        raise ValueError("로컬 AI URL은 localhost, host.docker.internal 또는 loopback 주소만 사용할 수 있습니다.")
    target_names = [str(target.get("column_name", "")).strip() for target in targets if str(target.get("column_name", "")).strip()]
    response_schema = {
        "type": "object",
        "properties": {
            name: {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
            }
            for name in target_names
        },
        "required": target_names,
        "additionalProperties": False,
    }
    prompt = (
        "한국어 데이터 사전 설명 후보를 생성하세요. 설명이 비어 있는 대상 컬럼만 처리합니다. "
        "테이블명과 전체 컬럼 구조를 반드시 참고하고, 대상 컬럼과 다른 컬럼의 관계를 고려하세요. "
        "PK·인덱스·NULL 여부와 컬럼명 조합으로 업무적 의미를 추론하세요. 각 대상 컬럼마다 서로 다른 짧은 설명을 최대 4개 생성하세요. "
        "제공된 JSON Schema를 정확히 따르고 모든 대상 컬럼을 반드시 반환하세요.\n"
        + json.dumps({"table_name": table_name, "table_columns": table_columns[:100], "targets": targets}, ensure_ascii=False)
    )
    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False, "format": response_schema, "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode())
    parsed = json.loads(body.get("response", "{}"))
    result: dict[str, list[str]] = {}
    for key, value in parsed.items():
        values = value if isinstance(value, list) else [value]
        result[str(key)] = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))[:4]
    return result


def _ollama_table_description(table_name: str, columns: list[dict], model: str, base_url: str) -> list[str]:
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in _ALLOWED_LOCAL_HOSTS:
        raise ValueError("로컬 AI URL은 localhost, host.docker.internal 또는 loopback 주소만 사용할 수 있습니다.")
    prompt = (
        "한국어 데이터 사전의 테이블 설명 후보를 생성하세요. "
        "1순위는 20자 안팎으로 짧고 명확하게 작성하고, 2~4순위는 테이블의 주요 컬럼을 반영해 서로 다르게 작성하세요. "
        "최대 4개를 JSON 객체의 descriptions 배열로만 반환하세요.\n"
        + json.dumps({"table_name": table_name, "columns": columns[:100]}, ensure_ascii=False)
    )
    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode())
    parsed = json.loads(body.get("response", "{}"))
    values = parsed.get("descriptions", parsed.get("description", []))
    if isinstance(values, str):
        values = [values]
    descriptions = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))[:4]
    if not descriptions:
        raise ValueError("로컬 AI가 descriptions 필드를 반환하지 않았습니다.")
    return descriptions


def suggest_table_description(table_name: str, columns: list[dict], provider: str = "rules", model: str = "qwen3:latest") -> dict:
    name = str(table_name or "").strip()
    if provider == "ollama":
        try:
            descriptions = _ollama_table_description(
                name,
                [{"column_name": str(column.get("column_name", "")), "data_type": str(column.get("data_type", ""))} for column in columns],
                model,
                os.getenv("METAVAULT_LOCAL_AI_URL", "http://host.docker.internal:11434"),
            )
            suggestions = [{"rank": rank, "description": value, "confidence": max(0.65, 0.8 - (rank - 1) * 0.04), "method": "local-ollama"} for rank, value in enumerate(descriptions[:4], 1)]
            return {"description": suggestions[0]["description"], "suggestions": suggestions, "confidence": suggestions[0]["confidence"], "method": "local-ollama"}
        except Exception as error:
            logger.warning("로컬 테이블 설명 생성 실패; 오프라인 규칙으로 fallback합니다 (%s)", type(error).__name__)
    fallback = _table_candidates(name, columns)
    suggestions = [{"rank": rank, "description": value, "confidence": max(0.4, 0.55 - (rank - 1) * 0.04), "method": "offline-rules"} for rank, value in enumerate(fallback[:4], 1)]
    return {"description": suggestions[0]["description"], "suggestions": suggestions, "confidence": suggestions[0]["confidence"], "method": "offline-rules"}


def suggest_descriptions(
    columns: list[dict],
    provider: str = "rules",
    model: str = "qwen3:latest",
    table_name: str = "",
    table_columns: list[dict] | None = None,
) -> list[dict]:
    all_columns = table_columns or columns
    context_columns = [
        {
            "column_name": str(column.get("column_name", "")),
            "data_type": str(column.get("data_type", "")),
            "nullable": column.get("nullable"),
            "null_yn": column.get("null_yn"),
            "pk_yn": column.get("pk_yn"),
            "index_yn": column.get("index_yn"),
            "index_names": column.get("index_names") or [],
            "ordinal_position": column.get("ordinal_position"),
        }
        for column in all_columns
    ]
    missing = [
        {"column_name": str(column.get("column_name", "")), "data_type": str(column.get("data_type", ""))}
        for column in columns
        if not str(column.get("comments") or column.get("description") or "").strip()
    ]
    if not missing:
        return []
    local_values: dict[str, list[str]] = {}
    if provider == "ollama":
        try:
            local_values = _ollama_suggestions(
                missing,
                table_name,
                context_columns,
                model,
                os.getenv("METAVAULT_LOCAL_AI_URL", "http://host.docker.internal:11434"),
            )
        except Exception as error:
            logger.warning("로컬 설명 생성 실패; 오프라인 규칙으로 fallback합니다 (%s)", type(error).__name__)
    result = []
    context_names = [item["column_name"] for item in context_columns if item["column_name"]]
    for column in missing:
        name = column["column_name"]
        candidates = local_values.get(name) or _candidate_rules(name, column["data_type"])
        if not local_values.get(name) and table_name and name.upper() in {"ID", "NO", "KEY"}:
            candidates[0] = f"{table_name} 레코드를 식별하는 고유 식별자"
        method = "local-ollama" if name in local_values else "offline-rules"
        confidence = 0.8 if method == "local-ollama" else rule_description("", name, column["data_type"])[1]
        suggestions = [{"rank": rank, "description": value, "confidence": confidence if rank == 1 else max(0.45, confidence - rank * 0.04), "method": method} for rank, value in enumerate(candidates[:4], 1)]
        result.append({"column_name": name, "description": suggestions[0]["description"], "suggestions": suggestions, "confidence": suggestions[0]["confidence"], "method": method, "context_column_count": len(context_names)})
    return result


def _date_recommendation_rules(columns: list[dict]) -> dict:
    date_types = ("DATE", "DATETIME", "TIMESTAMP", "TIME")
    date_word = re.compile(r"(?:DATE|DAY|DT|DTE|YMD|YYYYMMDD|TIME)", re.I)
    created_word = re.compile(r"(?:CRT|CREATED|CREATE|CREATION|REGIST|REGISTERED|INSERT|입력|등록|생성)", re.I)
    changed_word = re.compile(r"(?:UPDT|UPDATE|UPDATED|MODIFIED|MODIFY|CHANGED|CHANGE|LAST|변경|수정)", re.I)
    candidates = []
    for column in columns:
        name = str(column.get("column_name", column.get("name", "")))
        data_type = str(column.get("data_type", column.get("type", "")))
        if not name:
            continue
        is_date = any(token in data_type.upper() for token in date_types) or (re.search(r"(?:CHAR|TEXT|STRING|VARCHAR)", data_type, re.I) and date_word.search(name))
        if not is_date:
            continue
        score = (100 if any(token in data_type.upper() for token in date_types) else 50) + (10 if date_word.search(name) else 0)
        candidates.append({"name": name, "score": score, "created": bool(created_word.search(name)), "changed": bool(changed_word.search(name))})
    created = sorted([item for item in candidates if item["created"]], key=lambda item: (-item["score"], item["name"]))
    changed = sorted([item for item in candidates if item["changed"]], key=lambda item: (-item["score"], item["name"]))
    partition = [created[0]["name"]] if created else ([candidates[0]["name"]] if candidates else [])
    update = changed if changed else created
    return {"partition_columns": partition[:1], "update_base_columns": [item["name"] for item in update]}


def recommend_date_columns(table_name: str, columns: list[dict], provider: str = "rules", model: str = "qwen3:latest") -> dict:
    fallback = _date_recommendation_rules(columns)
    if provider != "ollama":
        return {**fallback, "method": "offline-rules"}
    try:
        base_url = os.getenv("METAVAULT_LOCAL_AI_URL", "http://host.docker.internal:11434")
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in _ALLOWED_LOCAL_HOSTS:
            raise ValueError("non-local Ollama URL")
        prompt = (
            "한국어 데이터 적재 설정을 위해 날짜/시간 컬럼의 역할을 추천하세요. "
            "PARTITION_KEY는 생성일자 계열 중 최대 1개, UPDATE_BASE는 변경일자 계열을 우선해 여러 개 추천하고 변경일자가 없으면 생성일자 계열을 추천하세요. "
            "반드시 입력된 column_name 중에서만 선택하고 JSON 객체로 partition_columns 배열과 update_base_columns 배열만 반환하세요.\n"
            + json.dumps({"table_name": table_name, "columns": columns[:500]}, ensure_ascii=False)
        )
        request = Request(f"{base_url.rstrip('/')}/api/generate", data=json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0}}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode())
        parsed = json.loads(body.get("response", "{}"))
        valid = {str(column.get("column_name", column.get("name", ""))) for column in columns}
        partition = [str(name) for name in parsed.get("partition_columns", []) if str(name) in valid][:1]
        update = [str(name) for name in parsed.get("update_base_columns", []) if str(name) in valid and str(name) in set(fallback["update_base_columns"])]
        if not partition and not update:
            raise ValueError("empty recommendation")
        return {"partition_columns": partition or fallback["partition_columns"], "update_base_columns": update or fallback["update_base_columns"], "method": "local-ollama"}
    except Exception as error:
        logger.warning("날짜 컬럼 로컬 추천 실패; 오프라인 규칙으로 fallback합니다 (%s)", type(error).__name__)
        return {**fallback, "method": "offline-rules"}
