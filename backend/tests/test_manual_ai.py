import json

import pytest
from pydantic import ValidationError

from app.manual_ai import build_manual_prompt, validate_manual_response
from app.schemas import MetaTableConfigIn


SECRET = "test-secret"
METADATA = {
    "owner": "SALES",
    "table_name": "ORDERS",
    "object_type": "TABLE",
    "snapshot_id": 42,
    "columns": [
        {"column_name": "ORDER_ID", "data_type": "NUMBER", "null_yn": "N", "pk_yn": "N", "index_yn": "Y"},
        {"column_name": "CREATED_AT", "data_type": "TIMESTAMP", "null_yn": "N", "pk_yn": "N", "index_yn": "N"},
        {"column_name": "UPDATED_AT", "data_type": "TIMESTAMP", "null_yn": "Y", "pk_yn": "N", "index_yn": "N"},
    ],
}


def _response(envelope, **recommendations):
    return json.dumps({
        "schema_version": "1.0",
        "request_id": envelope["request_id"],
        "snapshot_fingerprint": envelope["snapshot_fingerprint"],
        "recommendations": {
            "table_descriptions": [],
            "column_descriptions": [],
            "pk_candidates": [],
            "partition_key_columns": [],
            "update_base_columns": [],
            **recommendations,
        },
    }, ensure_ascii=False)


def test_manual_provider_is_a_valid_setting():
    assert MetaTableConfigIn(description_ai_provider="manual").description_ai_provider == "manual"


def test_prompt_contains_only_sanitized_metadata_and_strict_contract():
    envelope = build_manual_prompt({
        **METADATA,
        "host": "db.internal",
        "username": "secret-user",
        "password": "secret-password",
        "rows": [{"ORDER_ID": 1234}],
    }, SECRET)

    prompt = envelope["prompt"]
    assert "secret-password" not in prompt
    assert "db.internal" not in prompt
    assert "secret-user" not in prompt
    assert '1234' not in prompt
    assert "Markdown 코드 펜스" in prompt
    assert envelope["request_id"] in prompt
    assert envelope["snapshot_fingerprint"] in prompt


def test_manual_response_rejects_tampered_request_id():
    envelope = build_manual_prompt(METADATA, SECRET)
    body = json.loads(_response(envelope))
    body["request_id"] = "tampered"
    with pytest.raises(ValueError, match="요청 식별자"):
        validate_manual_response(json.dumps(body), METADATA, SECRET)


def test_manual_response_rejects_unknown_column_and_multiple_partition_keys():
    envelope = build_manual_prompt(METADATA, SECRET)
    with pytest.raises(ValueError, match="존재하지 않는 컬럼"):
        validate_manual_response(_response(envelope, update_base_columns=["NOT_REAL"]), METADATA, SECRET)
    with pytest.raises(ValueError, match="최대 1개"):
        validate_manual_response(_response(envelope, partition_key_columns=["CREATED_AT", "UPDATED_AT"]), METADATA, SECRET)


def test_manual_response_returns_preview_without_applying_pk():
    envelope = build_manual_prompt(METADATA, SECRET)
    result = validate_manual_response(_response(
        envelope,
        table_descriptions=[{"value": "주문 기본 정보를 관리합니다.", "reason": "주문 컬럼 구성", "confidence": 0.91}],
        column_descriptions=[{"column_name": "ORDER_ID", "suggestions": [{"value": "주문 식별자", "reason": "ID 컬럼", "confidence": 0.95}]}],
        pk_candidates=[{"columns": ["ORDER_ID"], "reason": "식별자 후보", "confidence": 0.9}],
        partition_key_columns=["CREATED_AT"],
        update_base_columns=["UPDATED_AT"],
    ), METADATA, SECRET)

    assert result["valid"] is True
    assert result["recommendations"]["pk_candidates"][0]["requires_source_validation"] is True
    assert result["recommendations"]["partition_key_columns"] == ["CREATED_AT"]
    assert result["recommendations"]["update_base_columns"] == ["UPDATED_AT"]


def test_manual_response_rejects_markdown_code_fence():
    envelope = build_manual_prompt(METADATA, SECRET)
    with pytest.raises(ValueError, match="JSON 객체만"):
        validate_manual_response("```json\n" + _response(envelope) + "\n```", METADATA, SECRET)


def test_manual_response_repairs_only_extra_trailing_closing_brace():
    envelope = build_manual_prompt(METADATA, SECRET)

    result = validate_manual_response(_response(envelope) + "}", METADATA, SECRET)

    assert result["valid"] is True
    assert result["normalization_warnings"] == ["응답 끝의 불필요한 닫는 중괄호 1개를 제거했습니다."]


def test_manual_response_does_not_repair_arbitrary_trailing_text():
    envelope = build_manual_prompt(METADATA, SECRET)
    with pytest.raises(ValueError, match="JSON 형식"):
        validate_manual_response(_response(envelope) + "copilot", METADATA, SECRET)


def test_manual_response_skips_nullable_pk_candidate_with_warning():
    envelope = build_manual_prompt(METADATA, SECRET)
    result = validate_manual_response(_response(
        envelope,
        pk_candidates=[{"columns": ["UPDATED_AT"], "reason": "후보", "confidence": 0.8}],
    ), METADATA, SECRET)

    assert result["recommendations"]["pk_candidates"] == []
    assert any("NULL 허용" in warning for warning in result["normalization_warnings"])


def test_manual_response_skips_incompatible_date_keys_with_warning():
    metadata = {
        **METADATA,
        "columns": [*METADATA["columns"], {"column_name": "EVENT_TIMESTAMP", "data_type": "TIMESTAMP", "null_yn": "Y"}],
    }
    envelope = build_manual_prompt(metadata, SECRET)
    result = validate_manual_response(_response(
        envelope,
        partition_key_columns=["EVENT_TIMESTAMP"],
        update_base_columns=["EVENT_TIMESTAMP"],
    ), metadata, SECRET)

    assert result["recommendations"]["partition_key_columns"] == []
    assert result["recommendations"]["update_base_columns"] == []
    assert sum("제외" in warning for warning in result["normalization_warnings"]) == 2
