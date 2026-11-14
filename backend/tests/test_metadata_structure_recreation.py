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
