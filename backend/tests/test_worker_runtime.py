from datetime import datetime, timedelta, timezone
from threading import Barrier

from app.database import Base
from app.models import CollectionJob, CollectionRun, DataSource
from app.worker import worker_once
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[table for table in Base.metadata.sorted_tables if table.schema != "EAPET"],
    )
    return engine, Session(engine)


def test_worker_once_dispatches_queued_runs_to_executor():
    engine, session = make_session()
    source = DataSource(name="source", db_type="sqlite")
    job = CollectionJob(name="job", data_source=source, schemas=[])
    run = CollectionRun(job=job, status="queued", current_step="queued")
    session.add(run)
    session.commit()
    calls = []

    count = worker_once(session, lambda job_id, run_id: calls.append((job_id, run_id)))

    assert count == 1
    assert calls == [(job.id, run.id)]


def test_worker_once_recovers_stalled_running_runs():
    _, session = make_session()
    source = DataSource(name="source", db_type="sqlite")
    job = CollectionJob(name="job", data_source=source, schemas=[])
    run = CollectionRun(
        job=job,
        status="running",
        current_step="collect_schema",
        heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    session.add(run)
    session.commit()

    worker_once(session, lambda *_: None)

    session.refresh(run)
    assert run.status == "timeout"
    assert run.error_code == "WORKER_LOST"


def test_worker_once_executes_multiple_queued_runs_concurrently():
    _, session = make_session()
    sources = [DataSource(name=f"source-{index}", db_type="sqlite") for index in range(2)]
    jobs = [CollectionJob(name=f"job-{index}", data_source=sources[index], schemas=[]) for index in range(2)]
    runs = [
        CollectionRun(job=jobs[0], status="queued", current_step="queued"),
        CollectionRun(job=jobs[0], status="queued", current_step="queued"),
        CollectionRun(job=jobs[1], status="queued", current_step="queued"),
    ]
    session.add_all(runs)
    session.commit()
    started = Barrier(2)
    completed_run_ids = []

    def executor(job_id, run_id):
        started.wait(timeout=2)
        completed_run_ids.append(run_id)

    count = worker_once(session, executor)
    assert count == 2
    assert sorted(completed_run_ids) == [runs[0].id, runs[2].id]
