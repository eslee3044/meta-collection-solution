from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import CollectionJob, CollectionRun
from .scheduler import execute_job, recover_orphan_runs


logger = logging.getLogger(__name__)


def worker_once(session: Session, executor=execute_job) -> int:
    now = datetime.now(timezone.utc)
    recover_orphan_runs(
        session,
        now - timedelta(minutes=get_settings().worker_stale_minutes),
    )
    active_sources = (
        select(CollectionJob.data_source_id)
        .join(CollectionRun, CollectionRun.job_id == CollectionJob.id)
        .where(CollectionRun.status.in_(["running", "cancel_requested"]))
    )
    first_queued_per_source = (
        select(func.min(CollectionRun.id).label("run_id"))
        .join(CollectionJob, CollectionJob.id == CollectionRun.job_id)
        .where(
            CollectionRun.status == "queued",
            (CollectionRun.next_attempt_at.is_(None) | (CollectionRun.next_attempt_at <= now)),
            ~CollectionJob.data_source_id.in_(active_sources),
        )
        .group_by(CollectionJob.data_source_id)
        .subquery()
    )
    targets = session.execute(
        select(CollectionRun.job_id, CollectionRun.id)
        .join(first_queued_per_source, CollectionRun.id == first_queued_per_source.c.run_id)
        .order_by(CollectionRun.id)
        .limit(get_settings().collection_workers)
    ).all()
    # Do not hold the read transaction while long-running collection threads run.
    session.rollback()
    if not targets:
        return 0
    max_workers = min(max(1, get_settings().collection_workers), len(targets))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(executor, job_id, run_id) for job_id, run_id in targets]
        for future in futures:
            try:
                future.result()
            except Exception:
                logger.exception("collection worker task failed")
    return len(targets)


def run_worker() -> None:
    poll_seconds = max(1, get_settings().worker_poll_seconds)
    while True:
        with SessionLocal() as session:
            worker_once(session)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
