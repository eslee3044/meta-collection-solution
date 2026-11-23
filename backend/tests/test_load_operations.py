from app.load_operations import build_chunks, build_manifest, normalize_plan_input, plan_fingerprint, recommend_load_design


def test_large_initial_plan_creates_bounded_chunks_and_init_manifest():
    plan = normalize_plan_input({
        "system_cd": "ERP", "instance_name": "PRD", "owner": "APP", "table_name": "ORDERS",
        "load_mode": "INIT", "split_strategy": "PK_RANGE", "estimated_rows": 2_500_000,
        "target_chunk_rows": 1_000_000, "max_parallelism": 2, "source_pool": "oracle_erp_pool",
    })
    chunks = build_chunks(plan)
    manifest = build_manifest(plan, chunks)
    assert len(chunks) == 3
    assert sum(chunk["expected_rows"] for chunk in chunks) == 2_500_000
    assert manifest["load_mode"] == "INIT"
    assert manifest["max_parallelism"] == 2
    assert "load_chunks" in manifest["tasks"]
    assert manifest["plan_fingerprint"] == plan_fingerprint(plan)


def test_incremental_manifest_is_locked_to_watermark_and_separate_dag():
    plan = normalize_plan_input({
        "system_cd": "ERP", "instance_name": "PRD", "owner": "APP", "table_name": "ORDERS",
        "load_mode": "INCREMENTAL", "source_watermark": "2026-11-21T00:00:00+09:00",
    })
    manifest = build_manifest(plan, build_chunks(plan))
    assert manifest["dag_id"].startswith("MV_INCREMENTAL_")
    assert manifest["tasks"] == ["check_source", "read_watermark", "load_incremental", "validate_staging", "call_l0_procedure", "publish_l0", "save_watermark"]




def test_load_design_recommends_composite_for_large_pk_and_date_table():
    result = recommend_load_design(
        [{"column_name": "ORDER_ID", "data_type": "NUMBER", "pk_yn": "Y"}, {"column_name": "CREATED_AT", "data_type": "TIMESTAMP"}, {"column_name": "UPDATED_AT", "data_type": "TIMESTAMP"}],
        10_000_000,
        20_000_000_000,
        {"partition_columns": ["CREATED_AT"], "update_base_columns": ["UPDATED_AT"], "method": "offline-rules"},
    )
    assert result["split_strategy"] == "COMPOSITE"
    assert result["partition_columns"] == ["CREATED_AT"]
    assert result["update_base_columns"] == ["UPDATED_AT"]
    assert result["max_parallelism"] == 3
    assert result["method"] == "rules"
    try:
        normalize_plan_input({
            "system_cd": "ERP", "instance_name": "PRD", "owner": "APP", "table_name": "ORDERS",
            "max_parallelism": 0,
        })
    except ValueError as error:
        assert "병렬도" in str(error)
    else:
        raise AssertionError("invalid parallelism must be rejected")
