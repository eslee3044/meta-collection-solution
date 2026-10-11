from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import CollectionRun
from .scheduler import execute_job, recover_orphan_runs


def worker_once(session: Session, executor=execute_job) -> int:
    recover_orphan_runs(
        session,
        datetime.now(timezone.utc) - timedelta(minutes=get_settings().worker_stale_minutes),
    )
    runs = session.scalars(
        select(CollectionRun)
        .where(
            CollectionRun.status == "queued",
            (CollectionRun.next_attempt_at.is_(None) | (CollectionRun.next_attempt_at <= datetime.now(timezone.utc))),
        )
        .order_by(CollectionRun.id)
        .limit(get_settings().collection_workers)
    ).all()
    for run in runs:
        executor(run.job_id, run.id)
    return len(runs)


def run_worker() -> None:
    poll_seconds = max(1, get_settings().worker_poll_seconds)
    while True:
        with SessionLocal() as session:
            worker_once(session)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
