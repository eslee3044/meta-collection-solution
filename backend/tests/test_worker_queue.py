from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CollectionJob, CollectionRun, DataSource
from app.scheduler import claim_run, recover_orphan_runs


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[table for table in Base.metadata.sorted_tables if table.schema != "EAPET"],
    )
    return engine, Session(engine)


def test_claim_run_is_atomic_and_only_first_worker_wins():
    engine, session = make_session()
    source = DataSource(name="source", db_type="sqlite")
    job = CollectionJob(name="job", data_source=source, schemas=[])
    run = CollectionRun(job=job, status="queued", current_step="queued")
    session.add(run)
    session.commit()

    assert claim_run(session, run.id) is True
    assert claim_run(session, run.id) is False

    session.refresh(run)
    assert run.status == "running"
    assert run.current_step == "initializing"
    assert run.heartbeat_at is not None


def test_recover_orphan_runs_marks_only_stale_running_runs():
    engine, session = make_session()
    source = DataSource(name="source", db_type="sqlite")
    job = CollectionJob(name="job", data_source=source, schemas=[])
    stale = CollectionRun(
        job=job,
        status="running",
        current_step="collect_schema",
        heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    fresh = CollectionRun(
        job=job,
        status="running",
        current_step="collect_schema",
        heartbeat_at=datetime.now(timezone.utc),
    )
    session.add_all([stale, fresh])
    session.commit()

    recovered = recover_orphan_runs(session, datetime.now(timezone.utc) - timedelta(minutes=5))

    assert recovered == 1
    session.refresh(stale)
    session.refresh(fresh)
    assert stale.status == "timeout"
    assert stale.error_code == "WORKER_LOST"
    assert stale.current_step == "worker_lost"
    assert fresh.status == "running"
