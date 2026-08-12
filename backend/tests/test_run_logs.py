from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import list_run_logs
from app.models import CollectionJob, CollectionRun, RunLog


def test_run_logs_are_ordered_and_expose_step_details():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        job = CollectionJob(name="로그 테스트", data_source_id=1)
        session.add(job)
        session.flush()
        run = CollectionRun(job_id=job.id, status="failed")
        session.add(run)
        session.flush()
        session.add_all([
            RunLog(run_id=run.id, sequence=2, level="error", step="collect_schema", message="테이블 조회 실패", created_at=datetime.now(timezone.utc)),
            RunLog(run_id=run.id, sequence=1, level="info", step="connect", message="DB 연결 시작", created_at=datetime.now(timezone.utc)),
        ])
        session.commit()

        logs = list_run_logs(run.id, session, None)

    assert [log.sequence for log in logs] == [1, 2]
    assert logs[1].step == "collect_schema"
    assert logs[1].level == "error"
    assert logs[1].message == "테이블 조회 실패"
