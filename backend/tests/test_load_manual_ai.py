import json

import pytest

from app.load_manual_ai import build_load_prompt, validate_load_response


META = {
    "system_cd": "TEST",
    "instance_name": "ORA",
    "postfix": "",
    "owner": "APP",
    "table_name": "ORDERS",
    "db_type": "ORACLE",
    "estimated_rows": 5000000,
    "estimated_bytes": 900000000,
    "pool_slots": 2,
    "max_parallelism_allowed": 8,
    "columns": [
        {"column_name": "ORDER_ID", "data_type": "NUMBER", "nullable": False, "pk_yn": "Y", "partition_key_yn": "N", "update_base_yn": "N"},
        {"column_name": "CREATED_AT", "data_type": "TIMESTAMP", "nullable": True, "pk_yn": "N", "partition_key_yn": "Y", "update_base_yn": "N"},
        {"column_name": "UPDATED_AT", "data_type": "TIMESTAMP", "nullable": True, "pk_yn": "N", "partition_key_yn": "N", "update_base_yn": "Y"},
    ],
}


def response(envelope, **overrides):
    body = {
        "schema_version": "1.0",
        "request_id": envelope["request_id"],
        "identity_fingerprint": envelope["identity_fingerprint"],
        "load_mode": "INCREMENTAL",
        "split_strategy": "DATE_RANGE",
        "partition_columns": ["CREATED_AT"],
        "update_base_columns": ["UPDATED_AT"],
        "target_chunk_rows": 500000,
        "max_parallelism": 8,
        "confidence": 0.86,
        "reason": "생성일자와 변경일자를 기준으로 추천했습니다.",
        "risks": [],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def test_build_load_prompt_excludes_credentials_and_contains_json_contract():
    envelope = build_load_prompt({**META, "password": "DO_NOT_EXPORT", "connection_string": "DO_NOT_EXPORT"}, "secret")
    assert "DO_NOT_EXPORT" not in envelope["prompt"]
    assert "DATALAKE_LOAD_RECOMMENDATION" in envelope["prompt"]
    assert '"split_strategy"' in envelope["prompt"]


def test_validate_load_response_restricts_columns_and_adjusts_parallelism():
    envelope = build_load_prompt(META, "secret")
    result = validate_load_response(response(envelope), META, "secret")
    assert result["validation"]["status"] == "ADJUSTED"
    assert result["recommendation"]["max_parallelism"] == 2
    assert result["recommendation"]["partition_columns"] == ["CREATED_AT"]


def test_validate_load_response_rejects_unknown_column():
    envelope = build_load_prompt(META, "secret")
    with pytest.raises(ValueError, match="존재하지 않는 컬럼"):
        validate_load_response(response(envelope, partition_columns=["MISSING_AT"]), META, "secret")


def test_validate_load_response_rejects_multiple_partition_columns():
    envelope = build_load_prompt(META, "secret")
    with pytest.raises(ValueError, match="PARTITION KEY는 최대 1개"):
        validate_load_response(response(envelope, partition_columns=["CREATED_AT", "UPDATED_AT"]), META, "secret")
