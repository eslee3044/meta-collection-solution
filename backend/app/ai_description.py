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


def _ollama_suggestions(columns: list[dict], model: str, base_url: str) -> dict[str, str]:
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in _ALLOWED_LOCAL_HOSTS:
        raise ValueError("로컬 AI URL은 localhost, host.docker.internal 또는 loopback 주소만 사용할 수 있습니다.")
    prompt = (
        "한국어 데이터 사전 설명을 생성하세요. 설명이 비어 있는 컬럼만 처리합니다. "
        "컬럼명과 타입만 근거로 하며 추측을 과도하게 확장하지 마세요. "
        "JSON 객체로만 반환하세요. 키는 column_name, 값은 짧은 한국어 설명입니다.\n"
        + json.dumps(columns, ensure_ascii=False)
    )
    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode())
    parsed = json.loads(body.get("response", "{}"))
    return {str(key): str(value).strip() for key, value in parsed.items() if str(value).strip()}


def suggest_table_description(table_name: str, columns: list[dict], provider: str = "rules", model: str = "qwen3:latest") -> dict:
    name = str(table_name or "").strip()
    if provider == "ollama":
        try:
            local_values = _ollama_suggestions(
                [{"column_name": "__TABLE_DESCRIPTION__", "data_type": name, "columns": [str(column.get("column_name", "")) for column in columns[:100]]}],
                model,
                os.getenv("METAVAULT_LOCAL_AI_URL", "http://host.docker.internal:11434"),
            )
            if local_values.get("__TABLE_DESCRIPTION__"):
                return {"description": local_values["__TABLE_DESCRIPTION__"], "confidence": 0.8, "method": "local-ollama"}
        except Exception as error:
            logger.warning("로컬 테이블 설명 생성 실패; 오프라인 규칙으로 fallback합니다 (%s)", type(error).__name__)
    return {"description": f"{name} 테이블의 데이터를 관리합니다.", "confidence": 0.55, "method": "offline-rules"}


def suggest_descriptions(columns: list[dict], provider: str = "rules", model: str = "qwen3:latest") -> list[dict]:
    missing = [
        {"column_name": str(column.get("column_name", "")), "data_type": str(column.get("data_type", ""))}
        for column in columns
        if not str(column.get("comments") or column.get("description") or "").strip()
    ]
    if not missing:
        return []
    local_values: dict[str, str] = {}
    if provider == "ollama":
        try:
            local_values = _ollama_suggestions(missing, model, os.getenv("METAVAULT_LOCAL_AI_URL", "http://host.docker.internal:11434"))
        except Exception as error:
            logger.warning("로컬 설명 생성 실패; 오프라인 규칙으로 fallback합니다 (%s)", type(error).__name__)
            local_values = {}
    result = []
    for column in missing:
        name = column["column_name"]
        if name in local_values:
            result.append({"column_name": name, "description": local_values[name], "confidence": 0.8, "method": "local-ollama"})
        else:
            description, confidence = rule_description("", name, column["data_type"])
            result.append({"column_name": name, "description": description, "confidence": confidence, "method": "offline-rules"})
    return result
