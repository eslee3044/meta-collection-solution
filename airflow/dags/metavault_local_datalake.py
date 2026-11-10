from datetime import datetime
from pathlib import Path

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


with DAG(
    dag_id="metavault_local_datalake",
    description="MetaVault local DuckDB + Parquet load skeleton",
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
    extract = EmptyOperator(task_id="extract_to_st", doc="Replace with source extraction task.")
    dq = EmptyOperator(task_id="run_dq_checks", doc="Replace with count/PK/DQ checks.")
    merge = EmptyOperator(task_id="merge_to_l0", doc="Replace with DuckDB L0 MERGE task.")
    finish = EmptyOperator(task_id="finish")

    start >> verify >> extract >> dq >> merge >> finish
