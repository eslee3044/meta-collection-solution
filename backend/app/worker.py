from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import CollectionJob, CollectionRun
from .scheduler import execute_job, recover_orphan_runs


logger = logging.getLogger(__name__)


def _select_targets(session: Session, excluded_source_ids: set[int] | None = None):
    now = datetime.now(timezone.utc)
    active_sources = (
        select(CollectionJob.data_source_id)
        .join(CollectionRun, CollectionRun.job_id == CollectionJob.id)
        .where(CollectionRun.status.in_(["running", "cancel_requested"]))
    )
    source_filter = ~CollectionJob.data_source_id.in_(active_sources)
    if excluded_source_ids:
        source_filter = source_filter & ~CollectionJob.data_source_id.in_(excluded_source_ids)
    first_queued_per_source = (
        select(func.min(CollectionRun.id).label("run_id"))
        .join(CollectionJob, CollectionJob.id == CollectionRun.job_id)
        .where(
            CollectionRun.status == "queued",
            (CollectionRun.next_attempt_at.is_(None) | (CollectionRun.next_attempt_at <= now)),
            source_filter,
        )
        .group_by(CollectionJob.data_source_id)
        .subquery()
    )
    return session.execute(
        select(CollectionRun.job_id, CollectionRun.id, CollectionJob.data_source_id)
        .join(first_queued_per_source, CollectionRun.id == first_queued_per_source.c.run_id)
        .join(CollectionJob, CollectionJob.id == CollectionRun.job_id)
        .order_by(CollectionRun.id)
        .limit(get_settings().collection_workers)
    ).all()


def dispatch_queued_runs(session: Session, submit, excluded_source_ids: set[int] | None = None) -> int:
    """Submit currently eligible runs without waiting for submitted work."""
    targets = _select_targets(session, excluded_source_ids)
    session.rollback()
    for job_id, run_id, source_id in targets:
        submit(job_id, run_id, source_id)
    return len(targets)


def worker_once(session: Session, executor=execute_job) -> int:
    recover_orphan_runs(
        session,
        datetime.now(timezone.utc) - timedelta(minutes=get_settings().worker_stale_minutes),
    )
    futures = []
    with ThreadPoolExecutor(max_workers=max(1, get_settings().collection_workers)) as pool:
        dispatch_queued_runs(
            session,
            lambda job_id, run_id, _source_id: futures.append(pool.submit(executor, job_id, run_id)),
        )
        for future in futures:
            try:
                future.result()
            except Exception:
                logger.exception("collection worker task failed")
    return len(futures)


def run_worker() -> None:
    settings = get_settings()
    poll_seconds = max(1, settings.worker_poll_seconds)
    max_workers = max(1, settings.collection_workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        active: dict[int, Future] = {}
        while True:
            for source_id, future in list(active.items()):
                if future.done():
                    try:
                        future.result()
                    except Exception:
                        logger.exception("collection worker task failed")
                    del active[source_id]
            with SessionLocal() as session:
                recover_orphan_runs(
                    session,
                    datetime.now(timezone.utc) - timedelta(minutes=settings.worker_stale_minutes),
                )
                dispatch_queued_runs(
                    session,
                    lambda job_id, run_id, source_id: active.__setitem__(
                        source_id,
                        pool.submit(execute_job, job_id, run_id),
                    ),
                    set(active),
                )
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
