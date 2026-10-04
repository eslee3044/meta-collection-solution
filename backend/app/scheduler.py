from datetime import datetime, timedelta, timezone
import json

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import desc, select, update

from .capabilities import is_supported_db_type
from .collector import collect_schema
from .config import get_settings
from .database import SessionLocal
from .models import CollectionJob, CollectionRun, RunLog, SchemaSnapshot


class CollectionCancelled(Exception):
    """Raised when a collection run is cooperatively cancelled."""


def claim_run(session, run_id: int) -> bool:
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(CollectionRun)
        .where(CollectionRun.id == run_id, CollectionRun.status == "queued")
        .values(status="running", current_step="initializing", started_at=now, heartbeat_at=now)
    )
    session.commit()
    return result.rowcount == 1


def recover_orphan_runs(session, stale_before: datetime) -> int:
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.status == "running",
            CollectionRun.heartbeat_at.is_not(None),
            CollectionRun.heartbeat_at < stale_before,
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
    session.commit()
    return result.rowcount


def request_run_cancel(session, run_id: int) -> CollectionRun:
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.id == run_id,
            CollectionRun.status.in_(["queued", "running"]),

        )
        .values(status="cancel_requested", current_step="cancel_requested", cancel_requested_at=now, heartbeat_at=now)
    )
    if result.rowcount == 0:
        run = session.get(CollectionRun, run_id)
        if not run:
            raise ValueError("수집 실행 기록을 찾을 수 없습니다.")
        raise ValueError("이미 종료된 수집 실행은 취소할 수 없습니다.")
    session.commit()
    return session.get(CollectionRun, run_id)


def _is_cancel_requested(session, run_id: int) -> bool:
    status = session.scalar(select(CollectionRun.status).where(CollectionRun.id == run_id))
    return status == "cancel_requested"


scheduler = BackgroundScheduler(
    timezone="Asia/Seoul",
    executors={"default": {"type": "threadpool", "max_workers": get_settings().collection_workers}},
    job_defaults={"coalesce": False, "max_instances": 1},
)


def execute_job(job_id: int) -> int:
    with SessionLocal() as session:
        job = session.get(CollectionJob, job_id)
        if not job:
            raise ValueError("수집 작업을 찾을 수 없습니다.")
        run = CollectionRun(job_id=job.id, status="queued", current_step="queued")
        session.add(run)
        session.commit()
        if not claim_run(session, run.id):
            return run.id
        session.refresh(run)
        sequence = 0
        current_step = "initializing"

        def log(level: str, step: str, message: str, details: str | None = None, check_cancel: bool = True) -> None:
            nonlocal sequence
            if check_cancel and _is_cancel_requested(session, run.id):
                raise CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
            now = datetime.now(timezone.utc)
            run.current_step = step
            run.heartbeat_at = now
            if details:
                try:
                    parsed = json.loads(details)
                    run.current_schema = parsed.get("schema") or parsed.get("current_schema")
                except (TypeError, json.JSONDecodeError):
                    pass
            sequence += 1
            session.add(RunLog(run_id=run.id, sequence=sequence, level=level, step=step, message=message[:1000], details=details[:4000] if details else None))
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
            current_step = "save_snapshot"
            log("info", "save_snapshot", f"수집 결과를 저장합니다. 객체 {count}개")
            session.add(SchemaSnapshot(data_source_id=job.data_source_id, run_id=run.id, payload=payload, fingerprint=fingerprint))
            completed = session.execute(
                update(CollectionRun)
                .where(CollectionRun.id == run.id, CollectionRun.status == "running")
                .values(status="success", object_count=count, current_step="complete")
            )
            if completed.rowcount != 1:
                session.rollback()
                raise CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
            session.commit()
            run = session.get(CollectionRun, run.id)
            log("info", "complete", "수집이 정상적으로 완료되었습니다.", check_cancel=False)
        except CollectionCancelled as exc:
            run.status = "cancelled"
            run.cancelled_at = datetime.now(timezone.utc)
            run.current_step = "cancelled"
            run.error_code = "COLLECTION_CANCELLED"
            run.error_message = str(exc)[:4000]
            log("warning", "cancelled", "사용자 요청으로 수집을 취소했습니다.", str(exc), check_cancel=False)
        except Exception as exc:
            run.status, run.error_message = "failed", str(exc)[:4000]
            run.error_code = "COLLECTION_FAILED"
            log("error", current_step, f"수집 중 오류가 발생했습니다: {current_step}", str(exc), check_cancel=False)
        finally:
            run.finished_at = datetime.now(timezone.utc)
            run.heartbeat_at = run.finished_at
            session.commit()
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
            item = scheduler.add_job(execute_job, trigger, args=[job.id], id=f"collection:{job.id}", replace_existing=True, max_instances=1)
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
