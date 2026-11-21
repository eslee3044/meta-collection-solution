from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery
from google.oauth2 import service_account
import psycopg
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import DatalakeTarget, MetaTableConfig
from .schemas import DatalakeTargetConnectionIn
from .security import decrypt_credentials, encrypt_credentials

ConnectionTester = Callable[[DatalakeTargetConnectionIn], dict[str, Any]]

TARGET_DATABASE_NAMES = {
    "postgresql": "PostgreSQL",
    "bigquery": "BigQuery",
    "redshift": "Redshift",
}


def sync_meta_target_database(session: Session, target_type: str) -> str:
    """메타 등록 기본 대상 DB를 실제 Datalake 대상 종류와 일치시킨다."""
    target_database_name = TARGET_DATABASE_NAMES.get(target_type.lower())
    if not target_database_name:
        raise HTTPException(status_code=400, detail="지원하지 않는 Datalake 대상 종류입니다.")
    config = session.get(MetaTableConfig, 1)
    if not config:
        config = MetaTableConfig(id=1)
        session.add(config)
    config.target_database_name = target_database_name
    return target_database_name


def sync_meta_target_database_from_active_target(session: Session) -> str | None:
    """활성 Datalake Target을 메타 등록 기본 대상 DB의 유일한 기준값으로 사용한다."""
    target = session.scalar(
        select(DatalakeTarget)
        .where(DatalakeTarget.is_active.is_(True))
        .order_by(DatalakeTarget.id.desc())
    )
    if not target:
        config = session.get(MetaTableConfig, 1)
        return config.target_database_name if config else None
    return sync_meta_target_database(session, target.target_type)


def test_postgres_connection(
    payload: DatalakeTargetConnectionIn,
    *,
    connector: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    connect = connector or psycopg.connect
    try:
        with connect(
            host=payload.host,
            port=payload.port,
            dbname=payload.database,
            user=payload.username,
            password=payload.password,
            sslmode=payload.ssl_mode,
            connect_timeout=payload.connect_timeout,
            application_name="metavault-datalake-preflight",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version')")
                version_row = cursor.fetchone()
                if not version_row:
                    raise HTTPException(status_code=400, detail="PostgreSQL 서버 버전을 확인할 수 없습니다.")
                server_version = str(version_row[0])
                cursor.execute(
                    "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
                )
                privilege_row = cursor.fetchone()
                if not privilege_row or privilege_row[0] is not True:
                    raise HTTPException(
                        status_code=400,
                        detail="PostgreSQL Datalake 계정에 스키마 생성 권한이 부족합니다.",
                    )
                cursor.execute(
                    "CREATE TEMP TABLE metavault_connection_test "
                    "(id INTEGER PRIMARY KEY, value TEXT) ON COMMIT DROP"
                )
                cursor.execute(
                    "INSERT INTO metavault_connection_test (id, value) VALUES (%s, %s)",
                    (1, "preflight"),
                )
                cursor.execute(
                    "UPDATE metavault_connection_test SET value=%s WHERE id=%s",
                    ("verified", 1),
                )
                cursor.execute("DELETE FROM metavault_connection_test WHERE id=%s", (1,))
                cursor.execute("TRUNCATE TABLE metavault_connection_test")
            connection.rollback()
    except psycopg.errors.InsufficientPrivilege as exc:
        raise HTTPException(status_code=400, detail="PostgreSQL Datalake 계정에 임시 테이블 및 쓰기 권한이 부족합니다.") from exc
    except (psycopg.Error, OSError) as exc:
        raise HTTPException(status_code=400, detail="PostgreSQL 서버에 연결할 수 없거나 인증에 실패했습니다.") from exc
    return {
        "success": True,
        "server_version": server_version,
        "permissions": {"create_schema": True, "temporary_table": True, "write": True, "truncate": True},
    }


def test_bigquery_connection(
    payload: DatalakeTargetConnectionIn,
    *,
    credentials_factory: Callable[[dict[str, Any]], Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if payload.target_type != "bigquery":
        raise HTTPException(status_code=400, detail="BigQuery 접속정보가 아닙니다.")
    try:
        import json

        credentials_data = json.loads(payload.service_account_json or "")
        make_credentials = credentials_factory or service_account.Credentials.from_service_account_info
        credentials = make_credentials(credentials_data)
        make_client = client_factory or bigquery.Client
        client = make_client(project=payload.project_id, credentials=credentials, location=payload.location or None)
        client.get_dataset(f"{payload.project_id}.{payload.dataset}", timeout=payload.connect_timeout)
        client.query("SELECT 1", location=payload.location or None).result(timeout=payload.connect_timeout)
    except (GoogleAPIError, ValueError, TypeError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail="BigQuery Dataset에 연결할 수 없거나 조회 권한이 부족합니다.",
        ) from exc
    return {
        "success": True,
        "target_type": "bigquery",
        "permissions": {"dataset": True, "query": True},
    }


def test_redshift_connection(
    payload: DatalakeTargetConnectionIn,
    *,
    connector: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if payload.target_type != "redshift":
        raise HTTPException(status_code=400, detail="Redshift 접속정보가 아닙니다.")
    connect = connector or psycopg.connect
    try:
        with connect(
            host=payload.host,
            port=payload.port,
            dbname=payload.database,
            user=payload.username,
            password=payload.password,
            sslmode=payload.ssl_mode,
            connect_timeout=payload.connect_timeout,
            application_name="metavault-redshift-preflight",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                version_row = cursor.fetchone()
                if not version_row:
                    raise HTTPException(status_code=400, detail="Redshift 서버 버전을 확인할 수 없습니다.")
                server_version = str(version_row[0])
                cursor.execute("CREATE TEMP TABLE metavault_connection_test (id INTEGER, value VARCHAR(32))")
                cursor.execute("INSERT INTO metavault_connection_test (id, value) VALUES (%s, %s)", (1, "preflight"))
                cursor.execute("UPDATE metavault_connection_test SET value=%s WHERE id=%s", ("verified", 1))
                cursor.execute("DELETE FROM metavault_connection_test WHERE id=%s", (1,))
                cursor.execute("TRUNCATE TABLE metavault_connection_test")
            connection.rollback()
    except psycopg.errors.InsufficientPrivilege as exc:
        raise HTTPException(status_code=400, detail="Redshift Datalake 계정에 임시 테이블 및 쓰기 권한이 부족합니다.") from exc
    except (psycopg.Error, OSError) as exc:
        raise HTTPException(status_code=400, detail="Redshift 서버에 연결할 수 없거나 인증에 실패했습니다.") from exc
    return {
        "success": True,
        "target_type": "redshift",
        "server_version": server_version,
        "permissions": {"temporary_table": True, "write": True, "truncate": True},
    }


def test_target_connection(payload: DatalakeTargetConnectionIn) -> dict[str, Any]:
    if payload.target_type == "bigquery":
        return test_bigquery_connection(payload)
    if payload.target_type == "redshift":
        return test_redshift_connection(payload)
    return test_postgres_connection(payload)


def load_active_connection(session: Session) -> DatalakeTargetConnectionIn:
    item = session.scalar(
        select(DatalakeTarget)
        .where(DatalakeTarget.is_active.is_(True))
        .order_by(DatalakeTarget.id.desc())
    )
    if not item:
        raise HTTPException(status_code=404, detail="설정된 Datalake 대상을 찾을 수 없습니다.")
    if item.status != "connected":
        raise HTTPException(
            status_code=409,
            detail="Datalake 대상의 최근 연결 상태가 정상이 아닙니다. 시스템 관리에서 다시 연결을 확인하세요.",
        )
    return DatalakeTargetConnectionIn.model_validate(decrypt_credentials(item.secret_encrypted))


def target_status(session: Session) -> dict[str, Any]:
    item = session.scalar(
        select(DatalakeTarget)
        .where(DatalakeTarget.is_active.is_(True))
        .order_by(DatalakeTarget.id.desc())
    )
    settings = get_settings()
    if not item:
        return {
            "configured": False,
            "target_type": None,
            "status": "unconfigured",
            "credential_configured": False,
            "connection_summary": {},
            "dedicated_encryption_key": bool(settings.credential_encryption_key),
            "last_tested_at": None,
            "created_at": None,
            "updated_at": None,
        }
    payload = DatalakeTargetConnectionIn.model_validate(decrypt_credentials(item.secret_encrypted))
    if payload.target_type == "bigquery":
        summary = {"project_id": payload.project_id, "dataset": payload.dataset, "location": payload.location}
    else:
        summary = {
            "host": payload.host,
            "port": payload.port,
            "database": payload.database,
            "username": payload.username,
            "ssl_mode": payload.ssl_mode,
        }
    return {
        "configured": True,
        "target_type": item.target_type,
        "status": item.status,
        "credential_configured": bool(item.secret_encrypted),
        "connection_summary": summary,
        "dedicated_encryption_key": bool(settings.credential_encryption_key),
        "last_tested_at": item.last_tested_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def create_target(
    session: Session,
    payload: DatalakeTargetConnectionIn,
    *,
    actor: str,
    tester: ConnectionTester,
) -> dict[str, Any]:
    if session.scalar(select(DatalakeTarget).where(DatalakeTarget.is_active.is_(True))):
        raise HTTPException(status_code=409, detail="이미 설정된 Datalake 대상이 있습니다. 인증정보 교체를 사용하세요.")
    test_result = tester(payload)
    if not test_result.get("success"):
        raise HTTPException(status_code=400, detail="Datalake 연결 테스트를 통과하지 못했습니다.")
    now = datetime.now(timezone.utc)
    item = DatalakeTarget(
        target_type=payload.target_type,
        secret_encrypted=encrypt_credentials(payload.model_dump()),
        credential_version=1,
        status="connected",
        last_tested_at=now,
        last_test_message="연결 및 기본 권한 확인 완료",
        created_by=actor,
        updated_by=actor,
        is_active=True,
    )
    session.add(item)
    sync_meta_target_database(session, payload.target_type)
    session.commit()
    session.refresh(item)
    return target_status(session)


def replace_target(
    session: Session,
    payload: DatalakeTargetConnectionIn,
    *,
    actor: str,
    tester: ConnectionTester,
) -> dict[str, Any]:
    item = session.scalar(
        select(DatalakeTarget)
        .where(DatalakeTarget.is_active.is_(True))
        .order_by(DatalakeTarget.id.desc())
    )
    if not item:
        raise HTTPException(status_code=404, detail="설정된 Datalake 대상을 찾을 수 없습니다.")
    test_result = tester(payload)
    if not test_result.get("success"):
        raise HTTPException(status_code=400, detail="새 접속정보 연결 테스트를 통과하지 못했습니다. 기존 접속정보를 유지합니다.")
    item.target_type = payload.target_type
    item.secret_encrypted = encrypt_credentials(payload.model_dump())
    item.credential_version += 1
    item.status = "connected"
    item.last_tested_at = datetime.now(timezone.utc)
    item.last_test_message = "새 접속정보 연결 및 기본 권한 확인 완료"
    item.updated_by = actor
    sync_meta_target_database(session, payload.target_type)
    session.commit()
    session.refresh(item)
    return target_status(session)


def retest_target(
    session: Session,
    *,
    tester: ConnectionTester,
) -> dict[str, Any]:
    item = session.scalar(
        select(DatalakeTarget)
        .where(DatalakeTarget.is_active.is_(True))
        .order_by(DatalakeTarget.id.desc())
    )
    if not item:
        raise HTTPException(status_code=404, detail="설정된 Datalake 대상을 찾을 수 없습니다.")
    payload = DatalakeTargetConnectionIn.model_validate(decrypt_credentials(item.secret_encrypted))
    try:
        test_result = tester(payload)
    except HTTPException:
        item.status = "failed"
        item.last_tested_at = datetime.now(timezone.utc)
        item.last_test_message = "연결 테스트 실패"
        session.commit()
        raise
    item.status = "connected"
    item.last_tested_at = datetime.now(timezone.utc)
    item.last_test_message = "저장된 접속정보 연결 및 기본 권한 확인 완료"
    session.commit()
    return test_result
