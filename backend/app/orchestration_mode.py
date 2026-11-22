from __future__ import annotations

from typing import Literal

OrchestrationMode = Literal["MANIFEST_ONLY", "AIRFLOW_MANAGED"]


def validate_mode_change(
    requested_mode: str,
    *,
    current_mode: str,
    preflight_status: str = "UNKNOWN",
    active_runs: int = 0,
    active_schedule: bool = False,
) -> OrchestrationMode:
    normalized = requested_mode.strip().upper()
    if normalized not in {"MANIFEST_ONLY", "AIRFLOW_MANAGED"}:
        raise ValueError("지원하지 않는 Datalake 적재 실행 방식입니다.")
    if normalized == "AIRFLOW_MANAGED" and preflight_status != "READY":
        raise ValueError("Airflow 직접 운영으로 변경하려면 Airflow preflight를 먼저 통과해야 합니다.")
    if normalized != current_mode and active_runs:
        raise ValueError("실행 중인 적재가 있어 실행 방식을 변경할 수 없습니다.")
    if normalized != current_mode and active_schedule:
        raise ValueError("활성 증분 스케줄이 있어 실행 방식을 변경할 수 없습니다.")
    return normalized  # type: ignore[return-value]
