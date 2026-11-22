from pydantic import ValidationError

from app.schemas import LoadPlanRecommendationIn


def test_load_plan_recommendation_accepts_identity_only_and_rejects_metadata_extras():
    payload = LoadPlanRecommendationIn.model_validate({
        "system_cd": "ORA1", "instance_name": "METAVAULT_ORA_TEST", "postfix": "",
        "owner": "MV", "table_name": "MV_LAYOUT_TEST", "estimated_rows": 3,
    })
    assert payload.table_name == "MV_LAYOUT_TEST"
    try:
        LoadPlanRecommendationIn.model_validate({
            "system_cd": "ORA1", "instance_name": "METAVAULT_ORA_TEST", "owner": "MV", "table_name": "MV_LAYOUT_TEST", "columns": [],
        })
    except ValidationError as error:
        assert "columns" in str(error)
    else:
        raise AssertionError("metadata extras must be rejected")
