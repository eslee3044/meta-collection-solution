from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from .config import get_settings


def _safe_name(value: str, prefix: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    return f"{prefix}_{value or 'source'}"[:250]


def runtime_names(source_name: str) -> tuple[str, str]:
    key = _safe_name(source_name, "source")
    return f"{key}_conn", f"{key}_pool"


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any] | None]:
    settings = get_settings()
    if not settings.airflow_username or not settings.airflow_password:
        raise HTTPException(status_code=503, detail="Airflow 자동 준비 설정이 없습니다. 관리자에게 Airflow API 설정을 요청하세요.")
    url = f"{settings.airflow_api_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = base64.b64encode(f"{settings.airflow_username}:{settings.airflow_password}".encode()).decode()
    headers["Authorization"] = f"Basic {token}"
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raise HTTPException(status_code=502, detail=f"Airflow API 요청에 실패했습니다. HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Airflow API에 연결하지 못했습니다. Airflow 상태와 API 주소를 확인하세요.") from exc


def _airflow_health() -> dict[str, Any]:
    settings = get_settings()
    api_root = settings.airflow_api_url.rstrip("/")
    base = api_root[:-len("/api/v1")] if api_root.endswith("/api/v1") else api_root
    request = Request(f"{base}/health", headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode() or "{}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Airflow health endpoint에 연결하지 못했습니다.") from exc


def preflight() -> dict[str, Any]:
    settings = get_settings()
    checks: list[dict[str, str]] = []
    api_reachable = False
    scheduler_healthy = False
    try:
        health = _airflow_health()
        api_reachable = health.get("metadatabase", {}).get("status") == "healthy"
        scheduler_healthy = health.get("scheduler", {}).get("status") == "healthy"
        checks.append({"code": "AIRFLOW_API", "status": "PASS" if api_reachable else "FAIL", "message": "Airflow API 연결 정상" if api_reachable else "Airflow API 응답이 없습니다."})
        checks.append({"code": "SCHEDULER", "status": "PASS" if scheduler_healthy else "FAIL", "message": "Scheduler 정상" if scheduler_healthy else "Scheduler가 정상 상태가 아닙니다."})
    except HTTPException as error:
        checks.extend([
            {"code": "AIRFLOW_API", "status": "FAIL", "message": str(error.detail)},
            {"code": "SCHEDULER", "status": "FAIL", "message": "Airflow 연결 실패로 확인하지 못했습니다."},
        ])
    deploy_path = Path(settings.airflow_dag_deploy_path)
    path_ready = deploy_path.is_dir() and deploy_path.exists() and deploy_path.is_relative_to(Path("/var/lib/metavault")) and __import__("os").access(deploy_path, __import__("os").W_OK)
    checks.append({"code": "DAG_PATH", "status": "PASS" if path_ready else "FAIL", "message": "DAG 배포 경로 쓰기 가능" if path_ready else "DAG 배포 경로가 없거나 쓰기 권한이 없습니다."})
    timezone_ready = settings.airflow_dag_deploy_path != ""
    checks.append({"code": "TIMEZONE", "status": "PASS", "message": "Asia/Seoul"})
    status = "READY" if api_reachable and scheduler_healthy and path_ready and timezone_ready else "FAILED"
    return {"status": status, "checks": checks, "api_reachable": api_reachable, "scheduler_healthy": scheduler_healthy, "deploy_path_writable": path_ready, "import_error_count": 0, "service_account_configured": bool(settings.airflow_username and settings.airflow_password)}



def set_dag_paused(dag_id: str, paused: bool) -> None:
    status, _ = _request("PATCH", f"dags/{dag_id}", {"is_paused": paused})
    if status != 200:
        raise HTTPException(status_code=502, detail="Airflow DAG pause 상태를 변경하지 못했습니다.")

def trigger_dag(dag_id: str, *, conf: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"conf": conf or {}}
    if run_id:
        payload["dag_run_id"] = run_id
    status, response = _request("POST", f"dags/{dag_id}/dagRuns", payload)
    if status not in {200, 201} or not response:
        raise HTTPException(status_code=502, detail="Airflow DAG 실행 요청에 실패했습니다.")
    return {"dag_id": dag_id, "dag_run_id": response.get("dag_run_id"), "state": response.get("state", "queued"), "execution_date": response.get("execution_date")}


def get_dag(dag_id: str) -> dict[str, Any] | None:
    status, response = _request("GET", f"dags/{dag_id}")
    if status == 404:
        return None
    if status != 200 or not response:
        raise HTTPException(status_code=502, detail="Airflow DAG 상태를 조회하지 못했습니다.")
    return response


def list_dag_task_instances(dag_id: str, dag_run_id: str) -> list[dict[str, Any]]:
    status, response = _request("GET", f"dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances")
    if status == 404:
        return []
    if status != 200 or not response:
        raise HTTPException(status_code=502, detail="Airflow task 상태를 조회하지 못했습니다.")
    return response.get("task_instances", [])

def list_dag_runs(dag_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    status, response = _request("GET", f"dags/{dag_id}/dagRuns?limit={max(1, min(limit, 20))}&order_by=-execution_date")
    if status == 404:
        return []
    if status != 200 or not response:
        raise HTTPException(status_code=502, detail="Airflow DAG 실행 상태를 조회하지 못했습니다.")
    return response.get("dag_runs", [])


def prepare_source_runtime(*, source: Any, credential_mode: str, dedicated_username: str | None, dedicated_password: str | None, pool_slots: int, confirm_pool_resize: bool) -> dict[str, Any]:
    from .security import decrypt_json

    secret = decrypt_json(source.secret_encrypted) if source.secret_encrypted else {}
    if credential_mode == "dedicated":
        if not dedicated_username or not dedicated_password:
            raise HTTPException(status_code=400, detail="별도 적재 계정은 사용자명과 비밀번호를 모두 입력해야 합니다.")
        username, password = dedicated_username, dedicated_password
    else:
        username, password = source.username, secret.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="메타 수집 계정 접속정보가 등록되어 있지 않습니다.")

    connection_id, pool_name = runtime_names(source.name)
    connection_payload = {
        "connection_id": connection_id,
        "conn_type": source.db_type,
        "host": source.host,
        "port": source.port,
        "login": username,
        "password": password,
        "schema": source.database or None,
        "extra": json.dumps({"metavault_source_id": source.id, "credential_mode": credential_mode}),
    }
    status, _ = _request("GET", f"connections/{connection_id}")
    if status == 404:
        _request("POST", "connections", connection_payload)
        connection_action = "created"
    else:
        connection_action = "reused"

    status, pool = _request("GET", f"pools/{pool_name}")
    if status == 404:
        _request("POST", "pools", {"name": pool_name, "slots": pool_slots, "description": f"MetaVault source pool for {source.name}"})
        pool_action, effective_slots = "created", pool_slots
    else:
        effective_slots = int((pool or {}).get("slots", pool_slots))
        if effective_slots != pool_slots:
            if not confirm_pool_resize:
                return {"status": "CONFIRM_REQUIRED", "connection_id": connection_id, "connection_action": connection_action, "pool_name": pool_name, "current_slots": effective_slots, "requested_slots": pool_slots, "credential_mode": credential_mode}
            _request("PATCH", f"pools/{pool_name}", {"slots": pool_slots, "description": f"MetaVault source pool for {source.name}"})
            pool_action, effective_slots = "resized", pool_slots
        else:
            pool_action = "reused"
    return {"status": "READY", "connection_id": connection_id, "connection_action": connection_action, "pool_name": pool_name, "pool_action": pool_action, "pool_slots": effective_slots, "credential_mode": credential_mode}
