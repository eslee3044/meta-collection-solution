from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

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
            payload, count, fingerprint = collect_schema(job.data_source, job.schemas)
            session.add(SchemaSnapshot(data_source_id=job.data_source_id, run_id=run.id, payload=payload, fingerprint=fingerprint))
            run.status, run.object_count = "success", count
        except Exception as exc:
            run.status, run.error_message = "failed", str(exc)[:4000]
        finally:
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
        return run.id


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

