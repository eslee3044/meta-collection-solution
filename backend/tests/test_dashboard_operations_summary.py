from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.dependencies import current_user
from app.main import _dashboard_operations_summary, app
from app.models import CollectionJob, CollectionRun, DataSource, DatalakeLoadDag, DatalakeLoadPlan, DatalakeOrchestrationConfig, MetaLayoutChange, MetaTableExt


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("app.main._dashboard_run_cache", None)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        execution_options={"schema_translate_map": {"EAPET": None}},
    )
    Base.metadata.create_all(engine, tables=[
        DatalakeOrchestrationConfig.__table__,
        DatalakeLoadPlan.__table__,
        DatalakeLoadDag.__table__,
        DataSource.__table__, CollectionJob.__table__, CollectionRun.__table__,
        MetaTableExt.__table__, MetaLayoutChange.__table__,
    ])
    with Session(engine) as value:
        yield value


def add_plan(session, plan_id=1):
    session.add(DatalakeLoadPlan(
        id=plan_id, system_cd="MV", instance_name="dev", postfix="", owner="EAPET",
        table_name=f"TABLE_{plan_id}", table_type="TABLE", plan_fingerprint=f"fp-{plan_id}",
        initial_status="PLANNED", incremental_status="LOCKED",
    ))
    session.flush()


def test_manifest_only_keeps_database_counts_without_airflow(session):
    session.add(DatalakeOrchestrationConfig(id=1, mode="MANIFEST_ONLY", timezone="Asia/Seoul"))
    add_plan(session)
    session.add(DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="init_mv", status="DEPLOYED", manifest_json="{}"))
    session.commit()

    result = _dashboard_operations_summary(session)

    assert result["orchestration"]["airflow_status"] == "NOT_APPLICABLE"
    assert result["datalake_summary"]["plans_total"] == 1
    assert result["datalake_summary"]["dags_total"] == 1
    assert result["datalake_summary"]["dags_deployed"] == 1


def test_airflow_latest_run_states_are_aggregated(session, monkeypatch):
    session.add(DatalakeOrchestrationConfig(id=1, mode="AIRFLOW_MANAGED", timezone="Asia/Seoul"))
    add_plan(session, 1)
    add_plan(session, 2)
    session.add_all([
        DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="queued_dag", status="DEPLOYED", manifest_json="{}"),
        DatalakeLoadDag(plan_id=2, dag_type="INIT", dag_id="failed_dag", status="DRAFT", manifest_json="{}"),
    ])
    session.commit()
    monkeypatch.setattr("app.main.dashboard_latest_dag_run", lambda dag_id, *, timeout: {"state": "queued" if dag_id == "queued_dag" else "upstream_failed"})

    result = _dashboard_operations_summary(session)

    assert result["orchestration"]["airflow_status"] == "AVAILABLE"
    assert result["datalake_summary"]["latest_running_or_queued_dags"] == 1
    assert result["datalake_summary"]["latest_failed_dags"] == 1


def test_airflow_failure_returns_partial_database_summary(session, monkeypatch):
    session.add(DatalakeOrchestrationConfig(id=1, mode="AIRFLOW_MANAGED", timezone="Asia/Seoul"))
    add_plan(session)
    session.add(DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="broken_dag", status="DEPLOYED", manifest_json="{}"))
    session.commit()
    def offline(dag_id, *, timeout):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.main.dashboard_latest_dag_run", offline)

    result = _dashboard_operations_summary(session)

    assert result["orchestration"]["airflow_status"] == "UNAVAILABLE"
    assert result["datalake_summary"]["plans_total"] == 1
    assert result["datalake_summary"]["dags_deployed"] == 1
    assert "offline" not in str(result)
    assert result["datalake_summary"]["run_status"] == "UNAVAILABLE"
    assert result["datalake_summary"]["latest_failed_dags"] is None


@pytest.mark.parametrize("has_dag", [False, True])
def test_airflow_distinguishes_no_dags_from_no_runs(session, monkeypatch, has_dag):
    session.add(DatalakeOrchestrationConfig(id=1, mode="AIRFLOW_MANAGED", timezone="Asia/Seoul"))
    calls = []
    if has_dag:
        add_plan(session)
        session.add(DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="unrun_dag", status="DEPLOYED", manifest_json="{}"))

    def request(method, path, *, timeout=10):
        calls.append((method, path, timeout))
        if "dagRuns" in path:
            return 200, {"dag_runs": []}
        return 200, {"dag_id": "unrun_dag"}

    monkeypatch.setattr("app.airflow_control._request", request)
    result = _dashboard_operations_summary(session)
    assert result["orchestration"]["airflow_status"] == ("AVAILABLE" if has_dag else "UNKNOWN")
    assert result["datalake_summary"]["run_status"] == ("NO_RUNS" if has_dag else "NO_DAGS")
    assert result["datalake_summary"]["latest_failed_dags"] is None
    assert result["datalake_summary"]["latest_running_or_queued_dags"] is None
    assert _dashboard_operations_summary(session) == result
    assert len(calls) == int(has_dag)
    assert all(method == "GET" and "limit=1" in path and 0 < timeout <= 3 for method, path, timeout in calls)


@pytest.mark.parametrize("status,payload", [(404, None), (200, {"unexpected": []})])
def test_failed_lookup_discards_earlier_airflow_results(session, monkeypatch, status, payload):
    session.add(DatalakeOrchestrationConfig(id=1, mode="AIRFLOW_MANAGED", timezone="Asia/Seoul"))
    add_plan(session)
    session.add_all([
        DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="first_dag", status="DEPLOYED", manifest_json="{}", updated_at=datetime(2025, 1, 2)),
        DatalakeLoadDag(plan_id=1, dag_type="INCREMENTAL", dag_id="second_dag", status="DEPLOYED", manifest_json="{}", updated_at=datetime(2025, 1, 1)),
    ])
    calls = []

    def request(method, path, *, timeout=10):
        calls.append(path)
        if "second_dag" in path:
            return status, payload
        return 200, {"dag_id": "first_dag", "dag_runs": [{"state": "failed"}]}

    monkeypatch.setattr("app.airflow_control._request", request)
    result = _dashboard_operations_summary(session)
    assert result["orchestration"]["airflow_status"] == "UNAVAILABLE"
    assert result["datalake_summary"]["run_status"] == "UNAVAILABLE"
    assert result["datalake_summary"]["dags_deployed"] == 2
    assert result["datalake_summary"]["latest_failed_dags"] is None
    assert result["datalake_summary"]["latest_running_or_queued_dags"] is None
    assert {item["source"] for item in result["datalake_summary"]["recent_activity"]} == {"datalake"}
    assert [path.split("/")[1] for path in calls] == ["first_dag", "second_dag"]


def test_plan_counts_require_matching_incremental_deployment(session):
    session.add(DatalakeOrchestrationConfig(id=1, mode="MANIFEST_ONLY", timezone="Asia/Seoul"))
    for plan_id in range(1, 5):
        add_plan(session, plan_id)
    for plan_id in (1, 2, 3):
        plan = session.get(DatalakeLoadPlan, plan_id)
        plan.initial_status = "COMPLETED"
        plan.incremental_status = "SCHEDULE_ACTIVE"
    session.add_all([
        DatalakeLoadDag(plan_id=1, dag_type="INCREMENTAL", dag_id="deployed_incremental", status="DEPLOYED", manifest_json="{}"),
        DatalakeLoadDag(plan_id=2, dag_type="INIT", dag_id="deployed_init", status="DEPLOYED", manifest_json="{}"),
        DatalakeLoadDag(plan_id=2, dag_type="INCREMENTAL", dag_id="draft_incremental", status="DRAFT", manifest_json="{}"),
        DatalakeLoadDag(plan_id=3, dag_type="INIT", dag_id="draft_init", status="DRAFT", manifest_json="{}"),
    ])

    summary = _dashboard_operations_summary(session)["datalake_summary"]

    assert summary["initial_status_counts"] == {"COMPLETED": 3, "PLANNED": 1}
    assert summary["incremental_status_counts"] == {
        "SCHEDULE_ACTIVE": 1, "SCHEDULE_PENDING_DEPLOYMENT": 2, "LOCKED": 1,
    }
    assert summary["init_dags_total"] == 2
    assert summary["init_dags_deployed"] == 1
    assert summary["dags_deployed"] == 2
    assert summary["run_status"] == "NOT_APPLICABLE"
    assert summary["latest_failed_dags"] is None
    assert summary["latest_running_or_queued_dags"] is None


@pytest.mark.parametrize("permission", [None, "sources:read", "jobs:read", "admin:*"])
def test_dashboard_activity_respects_route_permissions(session, monkeypatch, permission):
    session.add(DataSource(id=1, name="example database", db_type="sqlite"))
    session.add(CollectionJob(id=1, data_source_id=1, name="Daily catalog"))
    session.add(CollectionRun(job_id=1, status="failed", started_at=datetime(2025, 1, 1), error_message="raw failure detail"))
    session.add(DatalakeOrchestrationConfig(id=1, mode="AIRFLOW_MANAGED", timezone="Asia/Seoul"))
    add_plan(session)
    session.add_all([
        DatalakeLoadDag(plan_id=1, dag_type="INIT", dag_id="init", status="DEPLOYED", manifest_json="{}"),
        DatalakeLoadDag(plan_id=1, dag_type="INCREMENTAL", dag_id="incremental", status="DRAFT", manifest_json="{}"),
    ])
    for day in range(2, 12):
        session.add(CollectionRun(job_id=1, status="success", started_at=datetime(2025, 1, day), object_count=2))
    session.commit()
    monkeypatch.setitem(app.dependency_overrides, get_session, lambda: session)
    if permission:
        user = SimpleNamespace(roles=[SimpleNamespace(permissions=[SimpleNamespace(code=permission)])])
        monkeypatch.setitem(app.dependency_overrides, current_user, lambda: user)
    calls = []

    def request(dag_id, *, timeout):
        calls.append(dag_id)
        if dag_id == "init":
            return {"state": "running", "start_date": "2025-01-02T01:00:00+09:00", "conf": {"secret": "not for dashboard"}}
        return None

    monkeypatch.setattr("app.main.dashboard_latest_dag_run", request)
    # Without entering the context manager, TestClient does not run app lifespan.
    response = TestClient(app).get("/api/dashboard")
    if permission is None:
        assert response.status_code == 401
        assert not calls
        return

    assert response.status_code == 200
    payload = response.json()
    assert (payload["sources"], payload["active_jobs"], payload["objects"], payload["failed_runs"]) == (1, 1, 20, 1)
    assert len(payload["recent_runs"]) == 8
    assert payload["recent_layout_changes"] == []
    activity = payload["operations_activity"]
    assert len(activity) == 8
    assert (activity[0]["source"], activity[0]["activity_type"], activity[0]["status"]) == ("metadata", "collection", "failed")
    assert "Daily catalog" in activity[0]["target"]
    assert "raw failure detail" not in str(activity)
    assert all(item["updated_at"].endswith("+00:00") for item in activity)
    if permission == "sources:read":
        assert {item["source"] for item in activity} == {"metadata"}
        assert "datalake_summary" not in payload and "orchestration" not in payload
        assert not calls
    else:
        assert (activity[1]["source"], activity[1]["activity_type"], activity[1]["status"]) == ("airflow", "initial_load", "running")
        assert activity[1]["updated_at"] == "2025-01-01T16:00:00+00:00"
        assert (activity[2]["source"], activity[2]["activity_type"], activity[2]["status"]) == ("datalake", "incremental_load", "UNDEPLOYED")
        assert "not for dashboard" not in str(payload)
        assert payload["datalake_summary"]["recent_activity"]
        assert "init" in calls
