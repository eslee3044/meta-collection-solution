from app.main import _compare_metadata_structure


def test_compare_metadata_structure_reports_column_and_index_differences():
    expected = {
        "columns": ["SYSTEM_CD", "TABLE_NAME"],
        "indexes": [{"name": "TB_META_system_cd_idx", "columns": ["SYSTEM_CD", "TABLE_NAME"]}],
    }
    actual = {
        "columns": ["SYSTEM_CD", "OWNER"],
        "indexes": [{"name": "TB_META_wrong_idx", "columns": ["OWNER"]}],
    }

    differences = _compare_metadata_structure(expected, actual)

    assert any("누락 컬럼: TABLE_NAME" in item for item in differences)
    assert any("추가 컬럼: OWNER" in item for item in differences)
    assert any("인덱스" in item for item in differences)


def test_compare_metadata_structure_returns_empty_for_same_columns_and_indexes():
    structure = {
        "columns": ["SYSTEM_CD", "TABLE_NAME"],
        "indexes": [{"name": "TB_META_system_cd_idx", "columns": ["SYSTEM_CD", "TABLE_NAME"]}],
    }

    assert _compare_metadata_structure(structure, structure) == []


def test_compare_metadata_structure_accepts_database_generated_unique_index_name():
    expected = {
        "columns": ["CHANGE_FINGERPRINT"],
        "indexes": [{"name": "", "columns": ["CHANGE_FINGERPRINT"], "unique": True}],
    }
    actual = {
        "columns": ["CHANGE_FINGERPRINT"],
        "indexes": [{"name": "TB_META_LAYOUT_CHANGES_EXT_CHANGE_FINGERPRINT", "columns": ["CHANGE_FINGERPRINT"], "unique": True}],
    }

    assert _compare_metadata_structure(expected, actual) == []


def test_meta_pk_candidate_model_has_required_columns_and_indexes():
    from app.models import MetaPkCandidate

    columns = {column.name: column for column in MetaPkCandidate.__table__.columns}
    assert set(columns) == {
        "CANDIDATE_ID", "SYSTEM_CD", "INSTANCE_NAME", "POSTFIX", "OWNER", "TABLE_NAME", "OBJECT_TYPE",
        "SRC_DATA_SOURCE_ID", "SRC_SNAPSHOT_ID", "CANDIDATE_RANK", "CANDIDATE_COLUMNS_JSON", "CANDIDATE_FINGERPRINT",
        "SOURCE_TYPE", "METHOD", "MODEL_NAME", "CONFIDENCE", "REASON", "STATUS", "VALIDATION_STATUS", "ROW_COUNT",
        "NULL_COUNT", "DUPLICATE_GROUP_COUNT", "VALIDATED_AT", "VALIDATION_MESSAGE", "CREATED_BY", "CREATED_AT",
        "REVIEWED_BY", "REVIEWED_AT", "APPLIED_BY", "APPLIED_AT",
    }
    assert columns["CANDIDATE_ID"].primary_key
    assert columns["CANDIDATE_FINGERPRINT"].unique
    assert columns["SRC_DATA_SOURCE_ID"].nullable
    assert columns["SRC_SNAPSHOT_ID"].nullable
    index_columns = {tuple(column.name for column in index.columns): index for index in MetaPkCandidate.__table__.indexes}
    assert ("SYSTEM_CD", "INSTANCE_NAME", "POSTFIX", "OWNER", "TABLE_NAME", "STATUS") in index_columns
    assert ("SRC_SNAPSHOT_ID",) in index_columns


def test_metadata_expected_structure_includes_pk_candidates_for_internal_and_external_ddl():
    from app.main import _metadata_expected_structure
    from app.models import MetaTableConfig

    config = MetaTableConfig(
        schema_name="EAPET",
        tables_table_name="TB_META_TABLES_EXT",
        columns_table_name="TB_META_COLUMNS_EXT",
    )
    for db_type in ("postgresql", "mysql", "mssql"):
        expected = _metadata_expected_structure(config, db_type)
        candidate = expected["TB_META_PK_CANDIDATES_EXT"]
        assert "CANDIDATE_ID" in candidate["columns"]
        assert "CANDIDATE_COLUMNS_JSON" in candidate["columns"]
        assert {tuple(index["columns"]) for index in candidate["indexes"]} >= {
            ("CANDIDATE_FINGERPRINT",),
            ("SYSTEM_CD", "INSTANCE_NAME", "POSTFIX", "OWNER", "TABLE_NAME", "STATUS"),
            ("SRC_SNAPSHOT_ID",),
        }
