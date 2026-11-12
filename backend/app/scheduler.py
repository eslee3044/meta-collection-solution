from datetime import datetime, timedelta, timezone
import json

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import desc, func, select, update

from .capabilities import is_supported_db_type
from .collector import collect_schema
from .config import get_settings
from .database import SessionLocal
from .models import CollectionJob, CollectionRun, DataSource, RunLog, SchemaSnapshot


class CollectionCancelled(Exception):
    """Raised when a collection run is cooperatively cancelled."""


class CollectionAborted(Exception):
    """Raised when a worker no longer owns the run."""


def is_retryable_error(error: Exception) -> bool:
    message = str(error).lower()
    permanent_markers = ("permission denied", "not authorized", "unsupported", "invalid sql")
    transient_markers = ("timeout", "connection", "temporarily", "connection reset", "unavailable")
    return not any(marker in message for marker in permanent_markers) and (
        isinstance(error, (ConnectionError, TimeoutError)) or any(marker in message for marker in transient_markers)
    )


def calculate_retry_delay(attempt_count: int, base_seconds: int) -> int:
    return base_seconds * (2 ** max(0, attempt_count - 1))


def schedule_retry(session, run: CollectionRun, error: Exception, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if run.attempt_count >= run.max_attempts or not is_retryable_error(error):
        return False
    delay = calculate_retry_delay(run.attempt_count, get_settings().retry_base_seconds)
    result = session.execute(
        update(CollectionRun)
        .where(CollectionRun.id == run.id, CollectionRun.status == "running")
        .values(
            status="queued",
            current_step="retry_wait",
            error_code="RETRY_SCHEDULED",
            error_message=str(error)[:4000],
            next_attempt_at=now + timedelta(seconds=delay),
            finished_at=None,
            heartbeat_at=now,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True


def enqueue_run(session, job_id: int) -> CollectionRun:
    if not session.get(CollectionJob, job_id):
        raise ValueError("수집 작업을 찾을 수 없습니다.")
    run = CollectionRun(job_id=job_id, status="queued", current_step="queued")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def claim_run(session, run_id: int) -> bool:
    now = datetime.now(timezone.utc)
    source_id = session.scalar(
        select(CollectionJob.data_source_id)
        .join(CollectionRun, CollectionRun.job_id == CollectionJob.id)
        .where(CollectionRun.id == run_id)
    )
    if source_id is None:
        return False
    # PostgreSQL serializes claims for the same DataSource. Different sources
    # can still be claimed concurrently by different workers.
    session.execute(
        select(DataSource.id)
        .where(DataSource.id == source_id)
        .with_for_update()
    ).scalar_one()
    active_run = session.scalar(
        select(CollectionRun.id)
        .join(CollectionJob, CollectionJob.id == CollectionRun.job_id)
        .where(
            CollectionJob.data_source_id == source_id,
            CollectionRun.status.in_(["running", "cancel_requested"]),
        )
        .limit(1)
    )
    if active_run is not None:
        session.rollback()
        return False
    result = session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.id == run_id,
            CollectionRun.status == "queued",
            (CollectionRun.next_attempt_at.is_(None) | (CollectionRun.next_attempt_at <= now)),
        )
        .values(
            status="running",
            current_step="initializing",
            started_at=now,
            heartbeat_at=now,
            next_attempt_at=None,
            attempt_count=CollectionRun.attempt_count + 1,
        )
    )
    session.commit()
    return result.rowcount == 1


def dispatch_queued_runs(session, submit) -> int:
    queued_runs = session.scalars(
        select(CollectionRun)
        .where(CollectionRun.status == "queued")
        .order_by(CollectionRun.id)
    ).all()
    for run in queued_runs:
        submit(run.job_id, run.id)
    return len(queued_runs)


def recover_orphan_runs(session, stale_before: datetime) -> int:
    now = datetime.now(timezone.utc)
    running_last_seen = func.coalesce(CollectionRun.heartbeat_at, CollectionRun.started_at)
    running_result = session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.status == "running",
            running_last_seen.is_(None) | (running_last_seen < stale_before),
        )
        .values(
            status="timeout",
            current_step="worker_lost",
            finished_at=now,
            heartbeat_at=now,
            error_code="WORKER_LOST",
            error_message="Worker heartbeat가 만료되어 실행을 종료했습니다.",
        )
    )
    cancel_last_seen = func.coalesce(
        CollectionRun.heartbeat_at,
        CollectionRun.cancel_requested_at,
        CollectionRun.started_at,
    )
    cancelled_result = session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.status == "cancel_requested",
            cancel_last_seen.is_(None) | (cancel_last_seen < stale_before),
        )
        .values(
            status="cancelled",
            current_step="cancelled",
            cancelled_at=now,
            finished_at=now,
            heartbeat_at=now,
            error_code="COLLECTION_CANCELLED",
            error_message="Worker 재시작 후 오래된 취소 요청을 정리했습니다.",
        )
    )
    session.commit()
    return running_result.rowcount + cancelled_result.rowcount


def request_run_cancel(session, run_id: int) -> CollectionRun:
    now = datetime.now(timezone.utc)
    queued_result = session.execute(
        update(CollectionRun)
        .where(CollectionRun.id == run_id, CollectionRun.status == "queued")
        .values(
            status="cancelled",
            current_step="cancelled",
            cancel_requested_at=now,
            cancelled_at=now,
            finished_at=now,
            heartbeat_at=now,
            error_code="COLLECTION_CANCELLED",
            error_message="대기 중인 수집을 사용자가 취소했습니다.",
        )
    )
    if queued_result.rowcount == 1:
        session.commit()
        return session.get(CollectionRun, run_id)

    running_result = session.execute(
        update(CollectionRun)
        .where(CollectionRun.id == run_id, CollectionRun.status == "running")
        .values(
            status="cancel_requested",
            current_step="cancel_requested",
            cancel_requested_at=now,
            heartbeat_at=now,
        )
    )
    if running_result.rowcount == 1:
        session.commit()
        return session.get(CollectionRun, run_id)

    session.rollback()
    run = session.get(CollectionRun, run_id)
    if not run:
        raise ValueError("수집 실행 기록을 찾을 수 없습니다.")
    raise ValueError("이미 종료된 수집 실행은 취소할 수 없습니다.")


def _is_cancel_requested(session, run_id: int) -> bool:
    status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run_id))
    return status in {"cancel_requested", "cancelled"}


scheduler = BackgroundScheduler(
    timezone="Asia/Seoul",
    executors={"default": {"type": "threadpool", "max_workers": get_settings().collection_workers}},
    job_defaults={"coalesce": False, "max_instances": 1},
)


def _submit_queued_run(job_id: int, run_id: int) -> None:
    scheduler.add_job(
        execute_job,
        DateTrigger(run_date=datetime.now(timezone.utc)),
        args=[job_id, run_id],
        id=f"run:{run_id}",
        replace_existing=True,
        max_instances=1,
    )


def execute_job(job_id: int, run_id: int | None = None) -> int:
    with SessionLocal() as session:
        job = session.get(CollectionJob, job_id)
        if not job:
            raise ValueError("수집 작업을 찾을 수 없습니다.")
        if run_id is None:
            run = enqueue_run(session, job.id)
        else:
            run = session.get(CollectionRun, run_id)
            if not run or run.job_id != job.id:
                raise ValueError("수집 실행 기록을 찾을 수 없습니다.")
        if not claim_run(session, run.id):
            return run.id
        session.refresh(run)
        sequence = 0
        current_step = "initializing"

        def log(level: str, step: str, message: str, details: str | None = None, check_cancel: bool = True, commit: bool = True) -> None:
            nonlocal sequence
            if check_cancel:
                status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run.id))
                if status in {"cancel_requested", "cancelled"}:
                    raise CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
                if status != "running":
                    raise CollectionAborted(f"실행 상태가 변경되어 중단합니다: {status}")
            now = datetime.now(timezone.utc)
            current_schema = run.current_schema
            if details:
                try:
                    parsed = json.loads(details)
                    current_schema = parsed.get("schema") or parsed.get("current_schema") or current_schema
                except (TypeError, json.JSONDecodeError):
                    pass
            if check_cancel:
                updated = session.execute(
                    update(CollectionRun)
                    .where(CollectionRun.id == run.id, CollectionRun.status == "running")
                    .values(current_step=step, current_schema=current_schema, heartbeat_at=now)
                )
                if updated.rowcount != 1:
                    session.rollback()
                    status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run.id))
                    if status in {"cancel_requested", "cancelled"}:
                        raise CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
                    raise CollectionAborted(f"실행 상태가 변경되어 중단합니다: {status}")
            sequence += 1
            session.add(RunLog(run_id=run.id, sequence=sequence, level=level, step=step, message=message[:1000], details=details[:4000] if details else None))
            if commit:
                session.commit()

        def progress(step: str, status: str, message: str, details: dict | None = None) -> None:
            level = "error" if status == "error" else "info"
            log(level, step, message, json.dumps({"status": status, **(details or {})}, ensure_ascii=False, default=str))

        try:
            current_step = "connect"
            log("info", "connect", "데이터 소스 연결을 시작합니다.")
            current_step = "collect_schema"
            log("info", "collect_schema", "스키마 메타데이터 수집을 시작합니다.")
            payload, count, fingerprint = collect_schema(job.data_source, job.schemas, job.collect_storage, job.collection_items, progress_callback=progress)
            schema_count = len(payload.get("schemas", []))
            table_count = sum(len(schema.get("tables", [])) for schema in payload.get("schemas", []))
            view_count = sum(len(schema.get("views", [])) for schema in payload.get("schemas", []))
            procedure_count = sum(len(schema.get("procedures", [])) for schema in payload.get("schemas", []))
            diagnostic = {
                "schemas": [schema.get("name") for schema in payload.get("schemas", [])],
                "table_count": table_count,
                "view_count": view_count,
                "procedure_count": procedure_count,
                "collection_items": job.collection_items,
                "requested_schemas": job.schemas,
                "skipped_schemas": payload.get("skipped_schemas", []),
                "collection_diagnostics": payload.get("collection_diagnostics", []),
            }
            log("info" if count else "warning", "collect_schema", f"수집 결과: 스키마 {schema_count}개, 테이블 {table_count}개, 뷰 {view_count}개, 프로시저 {procedure_count}개", json.dumps(diagnostic, ensure_ascii=False, default=str))
            if job.collect_storage:
                current_step = "storage_growth"
                log("info", "storage_growth", "스토리지 증감량을 계산합니다.")
                previous = session.scalar(
                    select(SchemaSnapshot)
                    .where(SchemaSnapshot.data_source_id == job.data_source_id)
                    .order_by(desc(SchemaSnapshot.captured_at))
                    .limit(1)
                )
                apply_storage_growth(payload, previous.payload if previous else None)
            else:
                previous = session.scalar(
                    select(SchemaSnapshot)
                    .where(SchemaSnapshot.data_source_id == job.data_source_id)
                    .order_by(desc(SchemaSnapshot.captured_at))
                    .limit(1)
                )
            current_step = "save_snapshot"
            log("info", "save_snapshot", f"수집 결과를 저장합니다. 객체 {count}개", commit=False)
            now = datetime.now(timezone.utc)
            snapshot = SchemaSnapshot(data_source_id=job.data_source_id, run_id=run.id, payload=payload, fingerprint=fingerprint)
            session.add(snapshot)
            session.flush()
            if previous:
                from .integration import snapshot_diff
                from .main import _persist_layout_changes
                _persist_layout_changes(session, previous, snapshot, snapshot_diff(previous.payload, payload))
            sequence += 1
            session.add(RunLog(run_id=run.id, sequence=sequence, level="info", step="complete", message="수집이 정상적으로 완료되었습니다."))
            completed = session.execute(
                update(CollectionRun)
                .where(CollectionRun.id == run.id, CollectionRun.status == "running")
                .values(
                    status="success",
                    object_count=count,
                    current_step="complete",
                    finished_at=now,
                    heartbeat_at=now,
                )
            )
            if completed.rowcount != 1:
                session.rollback()
                current_status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run.id))
                if current_status in {"cancel_requested", "cancelled"}:
                    raise CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
                return run.id
            session.commit()
        except CollectionCancelled as exc:
            now = datetime.now(timezone.utc)
            session.execute(
                update(CollectionRun)
                .where(CollectionRun.id == run.id, CollectionRun.status.in_(["running", "cancel_requested"]))
                .values(
                    status="cancelled",
                    cancelled_at=now,
                    finished_at=now,
                    heartbeat_at=now,
                    current_step="cancelled",
                    error_code="COLLECTION_CANCELLED",
                    error_message=str(exc)[:4000],
                )
            )
            session.add(RunLog(run_id=run.id, sequence=sequence + 1, level="warning", step="cancelled", message="사용자 요청으로 수집을 취소했습니다.", details=str(exc)[:4000]))
            session.commit()
        except CollectionAborted:
            session.rollback()
        except Exception as exc:
            current_status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run.id))
            if current_status in {"cancel_requested", "cancelled", "timeout"}:
                session.rollback()
            elif current_status == "running" and not schedule_retry(session, run, exc):
                now = datetime.now(timezone.utc)
                failed = session.execute(
                    update(CollectionRun)
                    .where(CollectionRun.id == run.id, CollectionRun.status == "running")
                    .values(
                        status="failed",
                        error_message=str(exc)[:4000],
                        error_code="COLLECTION_FAILED",
                        finished_at=now,
                        heartbeat_at=now,
                    )
                )
                if failed.rowcount == 1:
                    session.add(RunLog(run_id=run.id, sequence=sequence + 1, level="error", step=current_step, message=f"수집 중 오류가 발생했습니다: {current_step}", details=str(exc)[:4000]))
                    session.commit()
                else:
                    session.rollback()
        return run.id


def apply_storage_growth(payload: dict, previous_payload: dict | None) -> None:
    previous = {}
    if previous_payload:
        for schema in previous_payload.get("schemas", []):
            for table in schema.get("tables", []):
                storage = table.get("storage")
                if storage:
                    previous[(schema["name"], table["name"])] = storage.get("total_bytes")

    summary = {"data_bytes": 0, "index_bytes": 0, "total_bytes": 0, "growth_bytes": 0, "observed_tables": 0, "comparable_tables": 0}
    for schema in payload.get("schemas", []):
        for table in schema.get("tables", []):
            storage = table.get("storage")
            if not storage:
                continue
            summary["observed_tables"] += 1
            current = int(storage.get("total_bytes") or 0)
            old = previous.get((schema["name"], table["name"]))
            storage["previous_total_bytes"] = old
            storage["growth_bytes"] = current - old if old is not None else None
            storage["growth_percent"] = round((current - old) / old * 100, 2) if old else None
            for key in ("data_bytes", "index_bytes", "total_bytes"):
                summary[key] += int(storage.get(key) or 0)
            if old is not None:
                summary["comparable_tables"] += 1
                summary["growth_bytes"] += current - old
    payload["storage_summary"] = summary


def enqueue_scheduled_job(job_id: int) -> int:
    with SessionLocal() as session:
        return enqueue_run(session, job_id).id


def sync_jobs() -> None:
    scheduler.remove_all_jobs()
    with SessionLocal() as session:
        jobs = session.scalars(select(CollectionJob).where(CollectionJob.is_active.is_(True))).all()
        for job in jobs:
            if not is_supported_db_type(job.data_source.db_type):
                job.next_run_at = None
                continue
            if job.schedule_type == "cron":
                trigger = CronTrigger.from_crontab(job.cron, timezone="Asia/Seoul")
            elif job.schedule_type == "interval" and job.interval_minutes:
                trigger = IntervalTrigger(minutes=job.interval_minutes)
            else:
                continue
            item = scheduler.add_job(enqueue_scheduled_job, trigger, args=[job.id], id=f"collection:{job.id}", replace_existing=True, max_instances=1)
            job.next_run_at = item.next_run_time
        session.commit()


def start_scheduler() -> None:
    with SessionLocal() as session:
        recover_orphan_runs(
            session,
            datetime.now(timezone.utc) - timedelta(minutes=get_settings().worker_stale_minutes),
        )
    if not scheduler.running:
        scheduler.start()
    sync_jobs()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
