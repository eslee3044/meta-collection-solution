import pytest

from app.orchestration_mode import validate_mode_change


def test_manifest_only_is_default_and_airflow_managed_is_valid():
    assert validate_mode_change("MANIFEST_ONLY", current_mode="MANIFEST_ONLY") == "MANIFEST_ONLY"
    assert validate_mode_change("AIRFLOW_MANAGED", current_mode="MANIFEST_ONLY", preflight_status="READY") == "AIRFLOW_MANAGED"


def test_airflow_managed_requires_ready_preflight():
    with pytest.raises(ValueError, match="preflight"):
        validate_mode_change("AIRFLOW_MANAGED", current_mode="MANIFEST_ONLY", preflight_status="FAILED")


def test_mode_cannot_change_while_run_or_schedule_is_active():
    with pytest.raises(ValueError, match="실행 중"):
        validate_mode_change("MANIFEST_ONLY", current_mode="AIRFLOW_MANAGED", preflight_status="READY", active_runs=1)
    with pytest.raises(ValueError, match="스케줄"):
        validate_mode_change("MANIFEST_ONLY", current_mode="AIRFLOW_MANAGED", preflight_status="READY", active_schedule=True)
