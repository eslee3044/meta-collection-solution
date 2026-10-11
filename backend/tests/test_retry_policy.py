from datetime import datetime, timedelta, timezone

from app.database import Base
from app.models import CollectionJob, CollectionRun, DataSource
from app.scheduler import calculate_retry_delay, is_retryable_error, schedule_retry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[table for table in Base.metadata.sorted_tables if table.schema != "EAPET"],
    )
    return engine, Session(engine)


def test_retry_policy_classifies_transient_errors_and_backoff():
    assert is_retryable_error(ConnectionError("connection reset")) is True
    assert is_retryable_error(PermissionError("permission denied")) is False
    assert calculate_retry_delay(1, 10) == 10
    assert calculate_retry_delay(2, 10) == 20


def test_schedule_retry_requeues_run_until_max_attempts():
    _, session = make_session()
    source = DataSource(name="source", db_type="sqlite")
    job = CollectionJob(name="job", data_source=source, schemas=[])
    run = CollectionRun(job=job, status="running", attempt_count=1, max_attempts=3)
    session.add(run)
    session.commit()

    schedule_retry(session, run, RuntimeError("connection timeout"), now=datetime.now(timezone.utc))

    session.refresh(run)
    assert run.status == "queued"
    assert run.error_code == "RETRY_SCHEDULED"
    assert run.next_attempt_at is not None
    assert run.finished_at is None
