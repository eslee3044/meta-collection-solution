from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.models import CollectionJob, CollectionRun, DataSource, RunLog, SchemaSnapshot
from app.scheduler import CollectionCancelled, request_run_cancel


def _lifecycle_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    DataSource.__table__.create(engine)
    CollectionJob.__table__.create(engine)
    CollectionRun.__table__.create(engine)
    RunLog.__table__.create(engine)
    SchemaSnapshot.__table__.create(engine)
    return engine


def test_run_has_lifecycle_and_heartbeat_fields():
    engine = _lifecycle_engine()
    with Session(engine) as session:
        run = CollectionRun(job_id=1, status="queued")
        session.add(run)
        session.flush()
        assert run.current_step == "queued"
        assert run.heartbeat_at is None
        assert run.cancel_requested_at is None
        assert run.cancelled_at is None
        assert run.error_code is None


def test_request_run_cancel_transitions_running_run():
    engine = _lifecycle_engine()
    with Session(engine) as session:
        run = CollectionRun(job_id=1, status="running", current_step="collect_schema")
        session.add(run)
        session.commit()

        cancelled = request_run_cancel(session, run.id)

        assert cancelled.status == "cancel_requested"
        assert cancelled.cancel_requested_at is not None
        assert cancelled.current_step == "cancel_requested"


def test_execute_job_cancellation_does_not_save_snapshot(monkeypatch):
    from app import scheduler

    engine = _lifecycle_engine()
    with Session(engine) as setup:
        source = DataSource(name="cancel-source", db_type="sqlite", database=":memory:")
        setup.add(source)
        setup.flush()
        job = CollectionJob(name="취소 실행", data_source_id=source.id, schemas=[])
        setup.add(job)
        setup.commit()
        job_id = job.id

    def fake_collect(*args, progress_callback=None, **kwargs):
        with Session(engine) as cancellation_session:
            run = cancellation_session.query(CollectionRun).order_by(CollectionRun.id.desc()).first()
            request_run_cancel(cancellation_session, run.id)
        progress_callback("collect_schema", "running", "수집 중")
        raise AssertionError("취소 후에는 수집 결과에 도달하면 안 됩니다")

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(scheduler, "collect_schema", fake_collect)
    run_id = scheduler.execute_job(job_id)

    with Session(engine) as session:
        run = session.get(CollectionRun, run_id)
        assert run.status == "cancelled"
        assert run.error_code == "COLLECTION_CANCELLED"
        assert session.query(SchemaSnapshot).count() == 0


def test_cancelled_progress_raises_without_saving_snapshot():
    error = CollectionCancelled("사용자가 실행 취소를 요청했습니다.")
    assert str(error) == "사용자가 실행 취소를 요청했습니다."
