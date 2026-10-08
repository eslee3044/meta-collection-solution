from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import CollectionRun
from .scheduler import execute_job


def worker_once(session: Session, executor=execute_job) -> int:
    runs = session.scalars(
        select(CollectionRun)
        .where(CollectionRun.status == "queued")
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
