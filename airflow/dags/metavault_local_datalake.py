import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator


DATALAKE_ROOT = Path("/var/lib/metavault/datalake")


def verify_local_datalake() -> None:
    required = [DATALAKE_ROOT / "st", DATALAKE_ROOT / "l0", DATALAKE_ROOT / "quarantine"]
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise RuntimeError(f"local Datalake directories are missing: {missing}")
    print(f"Local Datalake is ready: {DATALAKE_ROOT}")


def trigger_full_load(**context: Any) -> dict[str, Any]:
    conf = dict((context["dag_run"].conf or {}))
    required = ("job_id", "schema_name", "table_name", "key_columns")
    missing = [name for name in required if not conf.get(name)]
    if missing:
        raise ValueError(f"dag_run.conf is missing: {', '.join(missing)}")

    base_url = os.environ["METAVAULT_API_URL"].rstrip("/")
    response = requests.post(
        f"{base_url}/api/auth/login",
        json={
            "email": os.environ["METAVAULT_ADMIN_EMAIL"],
            "password": os.environ["METAVAULT_ADMIN_PASSWORD"],
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    load = requests.post(
        f"{base_url}/api/load/full",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "job_id": conf["job_id"],
            "schema_name": conf["schema_name"],
            "table_name": conf["table_name"],
            "key_columns": conf["key_columns"],
            "batch_id": conf.get("batch_id"),
            "chunk_size": conf.get("chunk_size", 5000),
        },
        timeout=conf.get("timeout_seconds", 3600),
    )
    if not load.ok:
        raise RuntimeError(f"MetaVault Full Load failed: HTTP {load.status_code}")
    result = load.json()
    if result.get("status") != "success":
        raise RuntimeError("MetaVault Full Load did not complete successfully")
    print({"run_id": result.get("run_id"), "source_count": result.get("source_count"), "l0": result.get("l0", {}).get("row_count")})
    return result


with DAG(
    dag_id="metavault_local_datalake",
    description="MetaVault Oracle Full Load to local DuckDB + Parquet",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["metavault", "datalake", "local"],
) as dag:
    start = EmptyOperator(task_id="start")
    verify = PythonOperator(
        task_id="verify_local_datalake",
        python_callable=verify_local_datalake,
    )
    load = PythonOperator(
        task_id="full_load_table",
        python_callable=trigger_full_load,
        doc_md="""
        Trigger with a table manifest, for example:
        {"job_id": 1, "schema_name": "APP", "table_name": "ORDERS", "key_columns": ["ORDER_ID"]}
        """,
    )
    finish = EmptyOperator(task_id="finish")

    start >> verify >> load >> finish
