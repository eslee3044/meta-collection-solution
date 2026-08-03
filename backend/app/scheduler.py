from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import desc, select

from .collector import collect_schema
from .database import SessionLocal
from .models import CollectionJob, CollectionRun, SchemaSnapshot


scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def execute_job(job_id: int) -> int:
    with SessionLocal() as session:
        job = session.get(CollectionJob, job_id)
        if not job:
            raise ValueError("수집 작업을 찾을 수 없습니다.")
        run = CollectionRun(job_id=job.id, status="running")
        session.add(run)
        session.commit()
        try:
            payload, count, fingerprint = collect_schema(job.data_source, job.schemas, job.collect_storage)
            if job.collect_storage:
                previous = session.scalar(
                    select(SchemaSnapshot)
                    .where(SchemaSnapshot.data_source_id == job.data_source_id)
                    .order_by(desc(SchemaSnapshot.captured_at))
                    .limit(1)
                )
                apply_storage_growth(payload, previous.payload if previous else None)
            session.add(SchemaSnapshot(data_source_id=job.data_source_id, run_id=run.id, payload=payload, fingerprint=fingerprint))
            run.status, run.object_count = "success", count
        except Exception as exc:
            run.status, run.error_message = "failed", str(exc)[:4000]
        finally:
            run.finished_at = datetime.now(timezone.utc)
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
    if not scheduler.running:
        scheduler.start()
    sync_jobs()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
