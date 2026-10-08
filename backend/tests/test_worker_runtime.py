from app.database import Base
from app.models import CollectionJob, CollectionRun, DataSource
from app.worker import worker_once
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def make_session():
    engine = create_engine("sqlite:///:memory:")
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
