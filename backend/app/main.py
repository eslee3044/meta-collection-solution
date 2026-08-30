from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import re
import secrets
from urllib.parse import quote
from typing import Any

import yaml
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import MetaData, Table, and_, desc, func, inspect, or_, select, text, update
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_session
from .dependencies import current_user, require
from .excel_export import build_schema_workbook
from .integration import ensure_integration_views, snapshot_diff, snapshot_summary
from .models import CollectionJob, CollectionRun, DataSource, Menu, MetaColumnExt, MetaTableConfig, MetaTableExt, Permission, Role, RunLog, SchemaSnapshot, User
from .capabilities import assert_supported_db_type
from .collector import available_schema_names, source_engine, test_source
from .scheduler import execute_job, start_scheduler, stop_scheduler, sync_jobs
from .schemas import DataSourceIn, DataSourceOut, JobIn, JobOut, LoginRequest, LoginResponse, MenuIn, MetaRegisterIn, MetaTableConfigIn, MetaTableConfigOut, PasswordChangeIn, RoleIn, RunLogOut, RunOut, UserIn, UserOut
from .security import create_token, decode_token, decrypt_json, encrypt_json, hash_password, verify_password
from .seed import seed


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, name=user.name, is_active=user.is_active,
        roles=[role.name for role in user.roles],
        permissions=sorted({p.code for role in user.roles for p in role.permissions}),
        menus=[menu.code for role in user.roles for menu in role.menus],
    )


def integration_auth(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    configured_key = get_settings().integration_api_key
    if configured_key:
        if not x_api_key or not secrets.compare_digest(x_api_key, configured_key):
            raise HTTPException(status_code=401, detail="유효한 연계 API 키가 필요합니다.")
        return session.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id))
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer 토큰 또는 연계 API 키가 필요합니다.")
    user = session.get(User, decode_token(authorization[7:]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="사용할 수 없는 계정입니다.")
    return user


@asynccontextmanager
async def lifespan(_: FastAPI):
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text('CREATE SCHEMA IF NOT EXISTS "EAPET"'))
    Base.metadata.create_all(engine)
    ensure_integration_views(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("collection_jobs")}
    if "collect_storage" not in columns:
        default = "FALSE" if engine.dialect.name == "postgresql" else "0"
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE collection_jobs ADD COLUMN collect_storage BOOLEAN NOT NULL DEFAULT {default}"))
    if "collection_items" not in columns:
        default_items = '["INDEX", "TABLE", "VIEW", "PROCEDURE", "SELECT PRIVILEGE"]'
        with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                connection.execute(text("ALTER TABLE collection_jobs ADD COLUMN collection_items JSONB NOT NULL DEFAULT '[\"INDEX\", \"TABLE\", \"VIEW\", \"PROCEDURE\", \"SELECT PRIVILEGE\"]'::jsonb"))
            else:
                connection.execute(text("ALTER TABLE collection_jobs ADD COLUMN collection_items JSON NOT NULL DEFAULT '[]'"))
                connection.execute(text("UPDATE collection_jobs SET collection_items = :items"), {"items": default_items})
    with SessionLocal() as session:
        for job in session.scalars(select(CollectionJob)).all():
            if set(job.collection_items or []) == {"INDEX", "TABLE", "VIEW", "PROCEDURE"}:
                job.collection_items = [*job.collection_items, "SELECT PRIVILEGE"]
        seed(session)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="MetaVault API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/capabilities")
def capabilities():
    from .capabilities import DOCKER_EXCLUDED_DB_TYPES, supported_db_types

    return {
        "deployment_mode": settings.deployment_mode,
        "supported_db_types": list(supported_db_types()),
        "excluded_db_types": list(DOCKER_EXCLUDED_DB_TYPES if settings.deployment_mode == "docker" else []),
    }


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    return LoginResponse(access_token=create_token(user.id), user=user_out(user))


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


@app.post("/api/auth/password")
def change_password(payload: PasswordChangeIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다.")
    if payload.current_password == payload.new_password:
        raise HTTPException(400, "새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    user.password_hash = hash_password(payload.new_password)
    session.commit()
    return {"status": "changed"}


@app.get("/api/dashboard")
def dashboard(session: Session = Depends(get_session), _: User = Depends(current_user)):
    latest = session.scalars(select(CollectionRun).order_by(desc(CollectionRun.started_at)).limit(8)).all()
    return {
        "sources": session.scalar(select(func.count()).select_from(DataSource)) or 0,
        "active_jobs": session.scalar(select(func.count()).select_from(CollectionJob).where(CollectionJob.is_active.is_(True))) or 0,
        "objects": session.scalar(select(func.coalesce(func.sum(CollectionRun.object_count), 0)).where(CollectionRun.status == "success")) or 0,
        "failed_runs": session.scalar(select(func.count()).select_from(CollectionRun).where(CollectionRun.status == "failed")) or 0,
        "recent_runs": [RunOut.model_validate(item) for item in latest],
    }


def apply_source(item: DataSource, payload: DataSourceIn) -> None:
    try:
        assert_supported_db_type(payload.db_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for field in ["name", "db_type", "host", "port", "database", "username", "options", "ssh_enabled", "ssh_host", "ssh_port", "ssh_username", "ssh_auth_type"]:
        setattr(item, field, getattr(payload, field))
    item.options = {**(payload.options or {}), "ssl_enabled": payload.ssl_enabled}
    secret = decrypt_json(item.secret_encrypted) if item.secret_encrypted else {}
    if payload.password is not None:
        secret["password"] = payload.password
    if payload.service_account_json is not None:
        try:
            credentials = json.loads(payload.service_account_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "서비스 계정 JSON 형식이 올바르지 않습니다.") from exc
        if not isinstance(credentials, dict) or not credentials.get("project_id") or not credentials.get("private_key"):
            raise HTTPException(400, "서비스 계정 JSON에 project_id와 private_key가 필요합니다.")
        secret["service_account"] = credentials
    if payload.ssl_enabled:
        for field in ["ssl_ca_cert", "ssl_cert", "ssl_key"]:
            value = getattr(payload, field)
            if value:
                secret[field] = value
    else:
        for field in ["ssl_ca_cert", "ssl_cert", "ssl_key"]:
            secret.pop(field, None)
    item.secret_encrypted = encrypt_json(secret) if secret else ""
    if payload.db_type == "bigquery":
        if not item.secret_encrypted:
            raise HTTPException(400, "BigQuery 서비스 계정 JSON을 입력하세요.")
        item.host = ""
        item.port = None
        item.username = ""
        item.ssh_enabled = False
    if payload.ssh_password is not None or payload.ssh_private_key is not None:
        item.ssh_secret_encrypted = encrypt_json({
            "password": payload.ssh_password,
            "private_key": payload.ssh_private_key,
            "private_key_passphrase": payload.ssh_private_key_passphrase,
        })


@app.get("/api/meta-table-config", response_model=MetaTableConfigOut)
def get_meta_table_config(session: Session = Depends(get_session), _: User = Depends(require("sources:read"))):
    config = session.get(MetaTableConfig, 1)
    if not config:
        config = MetaTableConfig(id=1)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def _check_external_meta_tables(source: DataSource, config: MetaTableConfig) -> None:
    metadata = MetaData()
    try:
        with source_engine(source) as external_engine, external_engine.connect() as connection:
            for table_name in (config.tables_table_name, config.columns_table_name):
                try:
                    Table(table_name, metadata, schema=config.schema_name, autoload_with=connection)
                except NoSuchTableError as error:
                    raise HTTPException(409, f"META_TABLES_MISSING:{config.schema_name}.{table_name}") from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"외부 DB 메타 테이블 확인에 실패했습니다: {error}") from error


@app.get("/api/meta-table-config/status")
def meta_table_config_status(session: Session = Depends(get_session), _: User = Depends(require("sources:read"))):
    config = session.get(MetaTableConfig, 1)
    if not config or config.source_type != "external":
        return {"status": "ready", "source_type": "internal", "missing_tables": []}
    source = session.get(DataSource, config.external_source_id) if config.external_source_id else None
    if not source:
        return {"status": "error", "source_type": "external", "missing_tables": [], "message": "외부 DB 접속정보가 없습니다."}
    try:
        _check_external_meta_tables(source, config)
        return {"status": "ready", "source_type": "external", "missing_tables": []}
    except HTTPException as error:
        if error.detail and str(error.detail).startswith("META_TABLES_MISSING:"):
            return {"status": "missing", "source_type": "external", "missing_tables": [str(error.detail).split(":", 1)[1]]}
        return {"status": "error", "source_type": "external", "missing_tables": [], "message": str(error.detail)}


@app.put("/api/meta-table-config", response_model=MetaTableConfigOut)
def update_meta_table_config(payload: MetaTableConfigIn, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")
    for value, label in ((payload.schema_name, "스키마명"), (payload.tables_table_name, "테이블명"), (payload.columns_table_name, "테이블명")):
        if not identifier.fullmatch(value):
            raise HTTPException(400, f"{label}은 영문자, 숫자, _, $, #만 사용할 수 있으며 숫자로 시작할 수 없습니다.")
    if payload.source_type == "external":
        if payload.external_source_id is None:
            raise HTTPException(400, "외부 DB를 선택해야 합니다.")
        if not session.get(DataSource, payload.external_source_id):
            raise HTTPException(404, "선택한 외부 DB 접속정보를 찾을 수 없습니다.")
    config = session.get(MetaTableConfig, 1)
    if not config:
        config = MetaTableConfig(id=1)
        session.add(config)
    config.source_type = payload.source_type
    config.external_source_id = payload.external_source_id if payload.source_type == "external" else None
    config.schema_name = payload.schema_name
    config.tables_table_name = payload.tables_table_name
    config.columns_table_name = payload.columns_table_name
    session.commit()
    if config.source_type == "external":
        source = session.get(DataSource, config.external_source_id) if config.external_source_id else None
        if not source:
            raise HTTPException(404, "설정된 외부 DB 접속정보를 찾을 수 없습니다.")
        _check_external_meta_tables(source, config)
    session.refresh(config)
    return config


@app.get("/api/sources", response_model=list[DataSourceOut])
def list_sources(session: Session = Depends(get_session), _: User = Depends(require("sources:read"))):
    return session.scalars(select(DataSource).order_by(DataSource.name)).all()


def _resolve_import_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_import_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_import_values(item) for item in value]
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            resolved = os.getenv(variable)
            if resolved is None:
                raise ValueError(f"환경변수 {variable}가 설정되지 않았습니다.")
            return resolved
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    return value


def _parse_import_list(filename: str, content: bytes, key: str) -> list[dict[str, Any]]:
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "Import 파일은 2MB 이하만 지원합니다.")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        text_content = content.decode("utf-8-sig")
        document = json.loads(text_content) if suffix == "json" else yaml.safe_load(text_content)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(400, "유효한 UTF-8 JSON 또는 YAML 파일이 아닙니다.") from exc
    if isinstance(document, dict):
        document = document.get(key)
    if not isinstance(document, list) or not document:
        raise HTTPException(400, f"최상위 {key} 배열이 필요합니다.")
    try:
        return [_resolve_import_values(item) for item in document]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _parse_source_import(filename: str, content: bytes) -> list[dict[str, Any]]:
    return _parse_import_list(filename, content, "connections")


_IMPORT_SECRET_FIELDS = {"password", "service_account_json", "ssl_ca_cert", "ssl_cert", "ssl_key", "ssh_password", "ssh_private_key", "ssh_private_key_passphrase"}


def _preview_source_item(item: dict[str, Any]) -> dict[str, Any]:
    safe = dict(item)
    for key in _IMPORT_SECRET_FIELDS:
        if key in safe and safe[key]:
            safe[key] = "[REDACTED]"
    return {"name": safe.get("name"), "db_type": safe.get("db_type"), "host": safe.get("host"), "port": safe.get("port"), "database": safe.get("database"), "username": safe.get("username"), "ssh_enabled": bool(safe.get("ssh_enabled") or (safe.get("ssh") or {}).get("enabled"))}


@app.post("/api/sources/import/preview")
async def preview_sources_import(file: UploadFile = File(...), _: User = Depends(require("sources:write"))):
    items = _parse_source_import(file.filename or "connections.yaml", await file.read())
    validated = []
    errors = []
    for index, raw in enumerate(items, start=1):
        try:
            if isinstance(raw.get("ssh"), dict):
                raw = {**raw, **{f"ssh_{key}": value for key, value in raw["ssh"].items() if key != "enabled"}, "ssh_enabled": raw["ssh"].get("enabled", True)}
            validated.append(_preview_source_item(DataSourceIn.model_validate(raw).model_dump(exclude_none=True)))
        except Exception as exc:
            errors.append({"row": index, "error": str(exc)[:500]})
    return {"total": len(items), "valid": len(validated), "errors": errors, "items": validated}


@app.post("/api/sources/import")
async def import_sources(file: UploadFile = File(...), duplicate: str = Query("skip", pattern="^(skip|overwrite|rename)$"), session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    items = _parse_source_import(file.filename or "connections.yaml", await file.read())
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    for index, raw in enumerate(items, start=1):
        try:
            if isinstance(raw.get("ssh"), dict):
                raw = {**raw, **{f"ssh_{key}": value for key, value in raw["ssh"].items() if key != "enabled"}, "ssh_enabled": raw["ssh"].get("enabled", True)}
            payload = DataSourceIn.model_validate(raw)
            existing = session.scalar(select(DataSource).where(DataSource.name == payload.name))
            if existing and duplicate == "skip":
                result["skipped"] += 1
                continue
            if existing and duplicate == "overwrite":
                apply_source(existing, payload)
                result["updated"] += 1
                continue
            if existing and duplicate == "rename":
                base = payload.name
                suffix = 2
                while session.scalar(select(DataSource).where(DataSource.name == f"{base} ({suffix})")):
                    suffix += 1
                payload = payload.model_copy(update={"name": f"{base} ({suffix})"})
            item = DataSource()
            apply_source(item, payload)
            session.add(item)
            result["created"] += 1
        except Exception as exc:
            result["errors"].append({"row": index, "error": str(exc)[:500]})
    session.commit()
    return result


@app.get("/api/sources/{source_id}/schemas", response_model=list[str])
def list_source_schemas(source_id: int, session: Session = Depends(get_session), _: User = Depends(require("sources:read"))):
    source = session.get(DataSource, source_id)
    if not source:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    try:
        return available_schema_names(source)
    except Exception as exc:
        raise HTTPException(400, f"스키마 목록을 불러오지 못했습니다: {str(exc)[:300]}") from exc


@app.post("/api/sources", response_model=DataSourceOut, status_code=201)
def create_source(payload: DataSourceIn, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    item = DataSource()
    apply_source(item, payload)
    session.add(item)
    session.commit()
    return item


@app.put("/api/sources/{source_id}", response_model=DataSourceOut)
def update_source(source_id: int, payload: DataSourceIn, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    item = session.get(DataSource, source_id)
    if not item:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    apply_source(item, payload)
    session.commit()
    return item


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: int, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    item = session.get(DataSource, source_id)
    if not item:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    session.delete(item)
    session.commit()


def _copy_source(item: DataSource) -> DataSource:
    clone = DataSource()
    for attribute in inspect(item).mapper.column_attrs:
        setattr(clone, attribute.key, getattr(item, attribute.key))
    return clone


def _test_source_payload(payload: DataSourceIn) -> dict[str, str]:
    item = DataSource()
    apply_source(item, payload)
    test_source(item)
    return {"status": "connected"}


@app.post("/api/sources/test")
def test_unsaved_connection(payload: DataSourceIn, _: User = Depends(require("sources:write"))):
    try:
        return _test_source_payload(payload)
    except Exception as exc:
        raise HTTPException(400, f"접속 실패: {str(exc)[:500]}") from exc


@app.post("/api/sources/{source_id}/test-edit")
def test_edit_connection(source_id: int, payload: DataSourceIn, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    item = session.get(DataSource, source_id)
    if not item:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    try:
        draft = _copy_source(item)
        apply_source(draft, payload)
        test_source(draft)
        return {"status": "connected"}
    except Exception as exc:
        raise HTTPException(400, f"접속 실패: {str(exc)[:500]}") from exc


@app.post("/api/sources/{source_id}/test")
def test_connection(source_id: int, session: Session = Depends(get_session), _: User = Depends(require("sources:write"))):
    item = session.get(DataSource, source_id)
    if not item:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    try:
        test_source(item)
        item.status = "connected"
    except Exception as exc:
        item.status = "failed"
        session.commit()
        raise HTTPException(400, f"접속 실패: {str(exc)[:500]}")
    item.last_tested_at = datetime.now(timezone.utc)
    session.commit()
    return {"status": "connected"}


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(session: Session = Depends(get_session), _: User = Depends(require("jobs:read"))):
    return session.scalars(select(CollectionJob).order_by(desc(CollectionJob.created_at))).all()


def _normalise_job_item(raw: dict[str, Any], session: Session) -> JobIn:
    item = dict(raw)
    source_ref = item.pop("data_source", None)
    if source_ref is not None and not item.get("data_source_id"):
        source = session.scalar(select(DataSource).where(DataSource.name == str(source_ref)))
        if not source:
            raise ValueError(f"데이터 소스 '{source_ref}'를 찾을 수 없습니다.")
        item["data_source_id"] = source.id
    return JobIn.model_validate(item)


def _preview_job_item(item: JobIn, session: Session) -> dict[str, Any]:
    source = session.get(DataSource, item.data_source_id)
    return {"name": item.name, "data_source": source.name if source else f"#{item.data_source_id}", "schedule_type": item.schedule_type, "cron": item.cron, "interval_minutes": item.interval_minutes, "schemas": item.schemas, "collection_items": item.collection_items, "collect_storage": item.collect_storage, "is_active": item.is_active}


@app.post("/api/jobs/import/preview")
async def preview_jobs_import(file: UploadFile = File(...), session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    items = _parse_import_list(file.filename or "jobs.yaml", await file.read(), "jobs")
    valid, errors = [], []
    for index, raw in enumerate(items, start=1):
        try:
            valid.append(_preview_job_item(_normalise_job_item(raw, session), session))
        except Exception as exc:
            errors.append({"row": index, "error": str(exc)[:500]})
    return {"total": len(items), "valid": len(valid), "errors": errors, "items": valid}


@app.post("/api/jobs/import")
async def import_jobs(file: UploadFile = File(...), duplicate: str = Query("skip", pattern="^(skip|overwrite|rename)$"), session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    items = _parse_import_list(file.filename or "jobs.yaml", await file.read(), "jobs")
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    for index, raw in enumerate(items, start=1):
        try:
            payload = _normalise_job_item(raw, session)
            if not session.get(DataSource, payload.data_source_id):
                raise ValueError(f"데이터 소스 #{payload.data_source_id}를 찾을 수 없습니다.")
            existing = session.scalar(select(CollectionJob).where(CollectionJob.name == payload.name))
            if existing and duplicate == "skip":
                result["skipped"] += 1
                continue
            if existing and duplicate == "overwrite":
                for key, value in payload.model_dump().items():
                    setattr(existing, key, value)
                result["updated"] += 1
                continue
            if existing and duplicate == "rename":
                base, suffix = payload.name, 2
                while session.scalar(select(CollectionJob).where(CollectionJob.name == f"{base} ({suffix})")):
                    suffix += 1
                payload = payload.model_copy(update={"name": f"{base} ({suffix})"})
            session.add(CollectionJob(**payload.model_dump()))
            result["created"] += 1
        except Exception as exc:
            result["errors"].append({"row": index, "error": str(exc)[:500]})
    session.commit()
    sync_jobs()
    return result


@app.post("/api/jobs", response_model=JobOut, status_code=201)
def create_job(payload: JobIn, session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    source = session.get(DataSource, payload.data_source_id)
    if not source:
        raise HTTPException(400, "데이터 소스를 찾을 수 없습니다.")
    try:
        assert_supported_db_type(source.db_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    item = CollectionJob(**payload.model_dump())
    session.add(item)
    session.commit()
    sync_jobs()
    session.refresh(item)
    return item


@app.put("/api/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: int, payload: JobIn, session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    item = session.get(CollectionJob, job_id)
    if not item:
        raise HTTPException(404, "수집 작업을 찾을 수 없습니다.")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    session.commit()
    sync_jobs()
    session.refresh(item)
    return item


@app.post("/api/jobs/{job_id}/run", status_code=202)
def run_job(job_id: int, tasks: BackgroundTasks, session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    job = session.get(CollectionJob, job_id)
    if not job:
        raise HTTPException(404, "수집 작업을 찾을 수 없습니다.")
    try:
        assert_supported_db_type(job.data_source.db_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    tasks.add_task(execute_job, job_id)
    return {"status": "accepted"}


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    item = session.get(CollectionJob, job_id)
    if not item:
        raise HTTPException(404, "수집 작업을 찾을 수 없습니다.")
    session.delete(item)
    session.commit()
    sync_jobs()


@app.get("/api/runs", response_model=list[RunOut])
def list_runs(session: Session = Depends(get_session), _: User = Depends(require("jobs:read"))):
    return session.scalars(select(CollectionRun).order_by(desc(CollectionRun.started_at)).limit(100)).all()


@app.get("/api/runs/{run_id}/logs", response_model=list[RunLogOut])
def list_run_logs(run_id: int, session: Session = Depends(get_session), _: User = Depends(require("jobs:read"))):
    if not session.get(CollectionRun, run_id):
        raise HTTPException(404, "수집 실행 기록을 찾을 수 없습니다.")
    return session.scalars(select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.sequence, RunLog.created_at)).all()


def _meta_table_script(config: MetaTableConfig, db_type: str) -> str:
    if db_type in {"mysql", "mariadb"}:
        quote_ident = lambda value: f"`{value.replace('`', '``')}`"
        varchar = "VARCHAR(255)"
        integer = "INT"
    elif db_type == "mssql":
        quote_ident = lambda value: f"[{value.replace(']', ']]')}]"
        varchar = "VARCHAR(255)"
        integer = "INT"
    else:
        quote_ident = lambda value: f'"{value.replace(chr(34), chr(34) * 2)}"'
        varchar = "VARCHAR(255)"
        integer = "INTEGER"
    schema = quote_ident(config.schema_name)
    table = quote_ident(config.tables_table_name)
    column = quote_ident(config.columns_table_name)
    table_key = ("," + chr(10) + "        ").join(f"{quote_ident(name)} {varchar} NOT NULL" for name in ["system_cd", "instance_name", "postfix", "owner", "table_name"])
    column_key = ("," + chr(10) + "        ").join(f"{quote_ident(name)} {varchar} NOT NULL" for name in ["system_cd", "instance_name", "postfix", "owner", "table_name", "column_name"])
    table_extra = [("database_name", varchar), ("etl_conn_div_cd", varchar), ("etl_conn_nm", varchar), ("tgt_ds_cd", varchar), ("tgt_table_name", varchar), ("tgt_database_name", varchar), ("instance_div_cd", varchar), ("comments", "TEXT"), ("table_type", varchar), ("partition_col_modifiable_yn", "CHAR(1)")]
    column_extra = [("column_id", integer), ("data_type", varchar), ("data_length", integer), ("data_precision", integer), ("data_scale", integer), ("null_yn", "CHAR(1)"), ("pk_yn", "CHAR(1)"), ("comments", "TEXT")]
    lines = [f"CREATE SCHEMA IF NOT EXISTS {schema};", "", f"CREATE TABLE {schema}.{table} (", f"        {table_key},"]
    lines.extend(f"        {quote_ident(name)} {kind}," for name, kind in table_extra)
    lines[-1] = lines[-1].rstrip(",") + ","
    lines.extend([f"        CONSTRAINT {quote_ident(config.tables_table_name + '_PK')} PRIMARY KEY ({', '.join(quote_ident(name) for name in ['system_cd', 'instance_name', 'postfix', 'owner', 'table_name'])})", ");", "", f"CREATE TABLE {schema}.{column} (", f"        {column_key},"])
    lines.extend(f"        {quote_ident(name)} {kind}," for name, kind in column_extra)
    lines[-1] = lines[-1].rstrip(",") + ","
    lines.extend([f"        CONSTRAINT {quote_ident(config.columns_table_name + '_PK')} PRIMARY KEY ({', '.join(quote_ident(name) for name in ['system_cd', 'instance_name', 'postfix', 'owner', 'table_name', 'column_name'])})", ");", ""])
    return chr(10).join(lines)


@app.get("/api/metadata/register-script")
def metadata_register_script(session: Session = Depends(get_session), _: User = Depends(require("metadata:write"))):
    config = session.get(MetaTableConfig, 1)
    if not config or config.source_type != "external" or config.external_source_id is None:
        raise HTTPException(400, "외부 DB 메타 등록 설정이 없습니다.")
    source = session.get(DataSource, config.external_source_id)
    if not source:
        raise HTTPException(404, "설정된 외부 DB 접속정보를 찾을 수 없습니다.")
    content = _meta_table_script(config, source.db_type)
    filename = f"metavault_meta_tables_{source.db_type}.sql"
    return Response(content=content, media_type="text/sql; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _register_metadata_external(payload: MetaRegisterIn, snapshot: SchemaSnapshot, source: DataSource, config: MetaTableConfig) -> tuple[int, int]:
    available = {table["name"]: (schema["name"], table) for schema in snapshot.payload.get("schemas", []) for table in schema.get("tables", [])}
    selected = set(payload.table_names)
    missing = sorted(selected - available.keys())
    if missing:
        raise HTTPException(400, f"수집 결과에 없는 테이블이 포함되어 있습니다: {', '.join(missing[:10])}")
    metadata = MetaData()
    try:
        with source_engine(source) as external_engine, external_engine.begin() as connection:
            try:
                tables = Table(config.tables_table_name, metadata, schema=config.schema_name, autoload_with=connection)
            except NoSuchTableError as error:
                raise HTTPException(409, f"META_TABLES_MISSING:{config.schema_name}.{config.tables_table_name}") from error
            try:
                columns = Table(config.columns_table_name, metadata, schema=config.schema_name, autoload_with=connection)
            except NoSuchTableError as error:
                raise HTTPException(409, f"META_TABLES_MISSING:{config.schema_name}.{config.columns_table_name}") from error
            table_columns = {column.name.lower(): column for column in tables.c}
            column_columns = {column.name.lower(): column for column in columns.c}
            table_keys = ["system_cd", "instance_name", "postfix", "owner", "table_name"]
            column_keys = [*table_keys, "column_name"]
            if any(key not in table_columns for key in table_keys) or any(key not in column_columns for key in column_keys):
                raise HTTPException(400, "외부 메타 테이블에 필요한 키 컬럼이 없습니다.")
            table_count = column_count = 0
            source_database = snapshot.payload.get("database") or ""
            for table_name in payload.table_names:
                owner, table = available[table_name]
                table_key = {"system_cd": payload.system_cd, "instance_name": snapshot.payload.get("source", ""), "postfix": payload.postfix, "owner": owner, "table_name": table_name}
                values = {**table_key, "database_name": source_database, "etl_conn_div_cd": payload.etl_conn_div_cd, "etl_conn_nm": payload.etl_conn_nm, "tgt_ds_cd": payload.tgt_ds_cd, "tgt_table_name": f"{table_name}{payload.target_name_suffix}", "tgt_database_name": payload.tgt_database_name, "instance_div_cd": payload.instance_div_cd, "table_type": "TABLE", "partition_col_modifiable_yn": "Y"}
                values = {name: value for name, value in values.items() if name in table_columns}
                where = and_(*[table_columns[key] == table_key[key] for key in table_keys])
                if connection.execute(select(tables).where(where)).first():
                    connection.execute(update(tables).where(where).values({table_columns[name]: value for name, value in values.items()}))
                else:
                    connection.execute(tables.insert().values({table_columns[name]: value for name, value in values.items()}))
                table_count += 1
                pk_names = set((table.get("primary_key") or {}).get("constrained_columns") or [])
                for position, column in enumerate(table.get("columns", []), start=1):
                    column_name = str(column.get("name", ""))
                    if not column_name or (payload.columns_by_table is not None and column_name not in set(payload.columns_by_table.get(table_name, []))):
                        continue
                    column_key = {**table_key, "column_name": column_name}
                    column_values = {**column_key, "column_id": int(column.get("ordinal_position") or position), "data_type": str(column.get("type") or ""), "data_length": int(column["length"]) if str(column.get("length", "")).isdigit() else None, "data_precision": int(column["precision"]) if str(column.get("precision", "")).isdigit() else None, "data_scale": int(column["scale"]) if str(column.get("scale", "")).isdigit() else None, "null_yn": "N" if column.get("nullable") is False else "Y", "pk_yn": "Y" if column_name in pk_names else "N", "comments": column.get("comment")}
                    column_values = {name: value for name, value in column_values.items() if name in column_columns}
                    column_where = and_(*[column_columns[key] == column_key[key] for key in column_keys])
                    if connection.execute(select(columns).where(column_where)).first():
                        connection.execute(update(columns).where(column_where).values({column_columns[name]: value for name, value in column_values.items()}))
                    else:
                        connection.execute(columns.insert().values({column_columns[name]: value for name, value in column_values.items()}))
                    column_count += 1
            return table_count, column_count
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"외부 DB 메타 테이블 등록에 실패했습니다: {error}") from error


@app.post("/api/metadata/register")
def register_metadata(payload: MetaRegisterIn, session: Session = Depends(get_session), _: User = Depends(require("metadata:write"))):
    snapshot = session.get(SchemaSnapshot, payload.snapshot_id)
    if not snapshot:
        raise HTTPException(404, "선택한 수집 스냅샷을 찾을 수 없습니다.")
    config = session.get(MetaTableConfig, 1)
    if config and config.source_type == "external":
        if config.external_source_id is None:
            raise HTTPException(400, "외부 DB 메타 등록 설정에 접속정보가 없습니다.")
        source = session.get(DataSource, config.external_source_id)
        if not source:
            raise HTTPException(404, "설정된 외부 DB 접속정보를 찾을 수 없습니다.")
        table_count, column_count = _register_metadata_external(payload, snapshot, source, config)
        return {"tables": table_count, "columns": column_count, "schema": config.schema_name, "status": "registered", "target": "external"}
    selected = set(payload.table_names)
    available = {table["name"]: (schema["name"], table) for schema in snapshot.payload.get("schemas", []) for table in schema.get("tables", [])}
    missing = sorted(selected - available.keys())
    if missing:
        raise HTTPException(400, f"수집 결과에 없는 테이블이 포함되어 있습니다: {', '.join(missing[:10])}")
    source_database = snapshot.payload.get("database") or ""
    table_count = column_count = 0
    for table_name in payload.table_names:
        schema_name, table = available[table_name]
        target_name = f"{table_name}{payload.target_name_suffix}"
        table_key = {"system_cd": payload.system_cd, "instance_name": snapshot.payload.get("source", ""), "postfix": payload.postfix, "owner": schema_name, "table_name": table_name}
        target = session.get(MetaTableExt, tuple(table_key.values()))
        if not target:
            target = MetaTableExt(**table_key)
            session.add(target)
        for key, value in {"database_name": source_database, "etl_conn_div_cd": payload.etl_conn_div_cd, "etl_conn_nm": payload.etl_conn_nm, "tgt_ds_cd": payload.tgt_ds_cd, "tgt_table_name": target_name, "tgt_database_name": payload.tgt_database_name, "instance_div_cd": payload.instance_div_cd, "table_type": "TABLE", "partition_col_modifiable_yn": "Y"}.items():
            setattr(target, key, value)
        table_count += 1
        pk_names = set((table.get("primary_key") or {}).get("constrained_columns") or [])
        for position, column in enumerate(table.get("columns", []), start=1):
            column_name = str(column.get("name", ""))
            if not column_name or (payload.columns_by_table is not None and column_name not in set(payload.columns_by_table.get(table_name, []))):
                continue
            column_key = {**table_key, "column_name": column_name}
            target_column = session.get(MetaColumnExt, tuple(column_key.values()))
            if not target_column:
                target_column = MetaColumnExt(**column_key)
                session.add(target_column)
            target_column.column_id = int(column.get("ordinal_position") or position)
            target_column.data_type = str(column.get("type") or "")
            target_column.data_length = int(column["length"]) if str(column.get("length", "")).isdigit() else None
            target_column.data_precision = int(column["precision"]) if str(column.get("precision", "")).isdigit() else None
            target_column.data_scale = int(column["scale"]) if str(column.get("scale", "")).isdigit() else None
            target_column.null_yn = "N" if column.get("nullable") is False else "Y"
            target_column.pk_yn = "Y" if column_name in pk_names else "N"
            target_column.comments = column.get("comment")
            column_count += 1
    session.commit()
    return {"tables": table_count, "columns": column_count, "schema": "configured", "status": "registered"}


def _registered_metadata_external(session: Session, config: MetaTableConfig, page: int, page_size: int, search: str, instance_name: str | None):
    source = session.get(DataSource, config.external_source_id) if config.external_source_id else None
    if not source:
        raise HTTPException(404, "설정된 외부 DB 접속정보를 찾을 수 없습니다.")
    metadata = MetaData()
    try:
        with source_engine(source) as external_engine, external_engine.connect() as connection:
            tables = Table(config.tables_table_name, metadata, schema=config.schema_name, autoload_with=connection)
            columns = Table(config.columns_table_name, metadata, schema=config.schema_name, autoload_with=connection)
            rows = [dict(row) for row in connection.execute(select(tables)).mappings().all()]
            if instance_name:
                rows = [row for row in rows if row.get("instance_name") == instance_name]
            if search:
                needle = search.lower()
                matching_columns = {row.get("table_name") for row in connection.execute(select(columns)).mappings().all() if needle in str(row.get("column_name") or "").lower()}
                rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("instance_name", "owner", "table_name")).lower() or row.get("table_name") in matching_columns]
            rows.sort(key=lambda row: (str(row.get("instance_name") or ""), str(row.get("owner") or ""), str(row.get("table_name") or "")))
            total = len(rows)
            page_rows = rows[(page - 1) * page_size:page * page_size]
            items = []
            for row in page_rows:
                key = {name: row.get(name) for name in ("system_cd", "instance_name", "postfix", "owner", "table_name")}
                column_rows = connection.execute(select(columns).where(and_(*[columns.c[name] == value for name, value in key.items()]))).mappings().all()
                items.append({**row, "comments": row.get("comments"), "columns": [dict(column) for column in column_rows]})
            source_counts = {}
            for row in rows:
                source_counts[row.get("instance_name")] = source_counts.get(row.get("instance_name"), 0) + 1
            return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size, "sources": sorted(source_counts), "source_counts": source_counts}
    except NoSuchTableError as error:
        raise HTTPException(409, "외부 메타 테이블이 없어 등록 메타를 조회할 수 없습니다.") from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"외부 DB 등록 메타 조회에 실패했습니다: {error}") from error


@app.get("/api/metadata/registered")
def registered_metadata(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str = Query("", max_length=100),
    instance_name: str | None = Query(None, max_length=100),
    session: Session = Depends(get_session),
    _: User = Depends(require("metadata:read")),
):
    config = session.get(MetaTableConfig, 1)
    if config and config.source_type == "external":
        return _registered_metadata_external(session, config, page, page_size, q.strip(), instance_name)
    query = select(MetaTableExt)
    search = q.strip()
    if instance_name:
        query = query.where(MetaTableExt.instance_name == instance_name)
    if search:
        pattern = f"%{search}%"
        column_match = select(MetaColumnExt.table_name).where(
            MetaColumnExt.system_cd == MetaTableExt.system_cd,
            MetaColumnExt.instance_name == MetaTableExt.instance_name,
            MetaColumnExt.postfix == MetaTableExt.postfix,
            MetaColumnExt.owner == MetaTableExt.owner,
            MetaColumnExt.table_name == MetaTableExt.table_name,
            MetaColumnExt.column_name.ilike(pattern),
        ).exists()
        query = query.where(or_(MetaTableExt.instance_name.ilike(pattern), MetaTableExt.owner.ilike(pattern), MetaTableExt.table_name.ilike(pattern), column_match))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    tables = session.scalars(query.order_by(MetaTableExt.instance_name, MetaTableExt.owner, MetaTableExt.table_name).offset((page - 1) * page_size).limit(page_size)).all()
    source_counts = {source: count for source, count in session.execute(select(MetaTableExt.instance_name, func.count()).group_by(MetaTableExt.instance_name)).all() if source}
    if not tables:
        return {"items": [], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size, "sources": sorted(source_counts), "source_counts": source_counts}
    keys = [(table.system_cd, table.instance_name, table.postfix, table.owner, table.table_name) for table in tables]
    columns = session.scalars(select(MetaColumnExt).where(or_(*[ (MetaColumnExt.system_cd == key[0]) & (MetaColumnExt.instance_name == key[1]) & (MetaColumnExt.postfix == key[2]) & (MetaColumnExt.owner == key[3]) & (MetaColumnExt.table_name == key[4]) for key in keys ])).order_by(MetaColumnExt.column_id)).all()
    grouped: dict[tuple, list] = {}
    for column in columns:
        key = (column.system_cd, column.instance_name, column.postfix, column.owner, column.table_name)
        grouped.setdefault(key, []).append({"column_name": column.column_name, "column_id": column.column_id, "data_type": column.data_type, "data_length": column.data_length, "data_precision": column.data_precision, "data_scale": column.data_scale, "null_yn": column.null_yn, "pk_yn": column.pk_yn, "comments": column.comments})
    items = [{"system_cd": table.system_cd, "instance_name": table.instance_name, "postfix": table.postfix, "owner": table.owner, "table_name": table.table_name, "database_name": table.database_name, "etl_conn_div_cd": table.etl_conn_div_cd, "etl_conn_nm": table.etl_conn_nm, "tgt_ds_cd": table.tgt_ds_cd, "tgt_table_name": table.tgt_table_name, "tgt_database_name": table.tgt_database_name, "comments": table.comments, "columns": grouped.get((table.system_cd, table.instance_name, table.postfix, table.owner, table.table_name), [])} for table in tables]
    sources = sorted({source for source in session.scalars(select(MetaTableExt.instance_name).distinct()).all() if source})
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size, "sources": sources, "source_counts": source_counts}


@app.put("/api/metadata/registered")
def update_registered_metadata(payload: dict, session: Session = Depends(get_session), _: User = Depends(require("metadata:write"))):
    key = (payload.get("system_cd"), payload.get("instance_name"), payload.get("postfix"), payload.get("owner"), payload.get("table_name"))
    if not all(isinstance(value, str) and value for value in key):
        raise HTTPException(422, "등록 메타의 키 값은 모두 필수입니다.")
    table = session.get(MetaTableExt, key)
    if not table:
        raise HTTPException(404, "등록된 메타 테이블을 찾을 수 없습니다.")
    for field in ("database_name", "etl_conn_div_cd", "etl_conn_nm", "tgt_ds_cd", "tgt_table_name", "tgt_database_name", "comments"):
        if field in payload:
            setattr(table, field, payload[field])
    items = payload.get("columns", [])
    valid_items = []
    for item in items:
        column_name = item.get("column_name")
        if not isinstance(column_name, str) or not column_name.strip():
            raise HTTPException(422, "컬럼명은 필수입니다.")
        for field in ("column_id", "data_length", "data_precision", "data_scale"):
            if field in item and item[field] is not None and (isinstance(item[field], bool) or not isinstance(item[field], int)):
                raise HTTPException(422, f"{field}는 숫자만 입력할 수 있습니다.")
        valid_items.append(item)
    column_names = [item["column_name"] for item in valid_items]
    columns = session.scalars(select(MetaColumnExt).where(
        MetaColumnExt.system_cd == key[0], MetaColumnExt.instance_name == key[1], MetaColumnExt.postfix == key[2], MetaColumnExt.owner == key[3], MetaColumnExt.table_name == key[4], MetaColumnExt.column_name.in_(column_names)
    )).all()
    columns_by_name = {column.column_name: column for column in columns}
    for item in valid_items:
        column = columns_by_name.get(item["column_name"])
        if not column:
            continue
        for field in ("data_type", "null_yn", "pk_yn", "comments"):
            if field in item:
                setattr(column, field, item[field])
        for field in ("column_id", "data_length", "data_precision", "data_scale"):
            if field in item:
                setattr(column, field, item[field])
    session.commit()
    return {"status": "updated"}


@app.get("/api/metadata")
def metadata(session: Session = Depends(get_session), _: User = Depends(require("metadata:read"))):
    snapshots = session.scalars(select(SchemaSnapshot).order_by(desc(SchemaSnapshot.captured_at))).all()
    seen, result = set(), []
    for item in snapshots:
        if item.data_source_id not in seen:
            result.append({"id": item.id, "data_source_id": item.data_source_id, "run_id": item.run_id, "captured_at": item.captured_at, "fingerprint": item.fingerprint, "payload": item.payload})
            seen.add(item.data_source_id)
    return result


@app.get("/api/integration/v1/sources")
def integration_sources(session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    return [{"id": source.id, "name": source.name, "db_type": source.db_type, "database": source.database, "status": source.status} for source in session.scalars(select(DataSource).order_by(DataSource.name)).all()]


@app.get("/api/integration/v1/sources/{source_id}/snapshots")
def integration_snapshot_history(source_id: int, limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    source = session.get(DataSource, source_id)
    if not source:
        raise HTTPException(404, "데이터 소스를 찾을 수 없습니다.")
    snapshots = session.scalars(select(SchemaSnapshot).where(SchemaSnapshot.data_source_id == source_id).order_by(desc(SchemaSnapshot.captured_at), desc(SchemaSnapshot.id)).limit(limit)).all()
    return [snapshot_summary(snapshot) for snapshot in snapshots]


@app.get("/api/integration/v1/snapshots/{snapshot_id}")
def integration_snapshot(snapshot_id: int, session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    snapshot = session.get(SchemaSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "snapshot을 찾을 수 없습니다.")
    return {**snapshot_summary(snapshot), "payload": snapshot.payload}


@app.get("/api/integration/v1/sources/{source_id}/latest")
def integration_latest_snapshot(source_id: int, session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    snapshot = session.scalar(select(SchemaSnapshot).where(SchemaSnapshot.data_source_id == source_id).order_by(desc(SchemaSnapshot.captured_at), desc(SchemaSnapshot.id)).limit(1))
    if not snapshot:
        raise HTTPException(404, "해당 데이터 소스의 snapshot이 없습니다.")
    return {**snapshot_summary(snapshot), "payload": snapshot.payload}


@app.get("/api/integration/v1/sources/{source_id}/diff")
def integration_snapshot_diff(source_id: int, from_snapshot_id: int, to_snapshot_id: int, session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    before = session.get(SchemaSnapshot, from_snapshot_id)
    after = session.get(SchemaSnapshot, to_snapshot_id)
    if not before or not after or before.data_source_id != source_id or after.data_source_id != source_id:
        raise HTTPException(404, "같은 데이터 소스의 유효한 snapshot 두 개가 필요합니다.")
    return snapshot_diff(before, after)


@app.get("/api/integration/v1/snapshots/{snapshot_id}/objects")
def integration_snapshot_objects(snapshot_id: int, schema_name: str | None = None, kind: str | None = None, session: Session = Depends(get_session), _: User = Depends(integration_auth)):
    snapshot = session.get(SchemaSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "snapshot을 찾을 수 없습니다.")
    allowed = {"schema", "table", "column", "index", "view", "procedure"}
    if kind and kind not in allowed:
        raise HTTPException(400, f"kind는 {', '.join(sorted(allowed))} 중 하나여야 합니다.")
    objects = []
    payload = snapshot.payload or {}
    for schema in payload.get("schemas", []):
        if schema_name and schema.get("name") != schema_name:
            continue
        for object_kind, values in (("table", schema.get("tables", [])), ("view", schema.get("views", [])), ("procedure", schema.get("procedures", []))):
            if not kind or kind == object_kind:
                objects.extend({"kind": object_kind, "schema": schema.get("name"), **value} for value in values)
            if object_kind == "table" and (not kind or kind in {"column", "index"}):
                for table in values:
                    if kind in (None, "column"):
                        objects.extend({"kind": "column", "schema": schema.get("name"), "table": table.get("name"), **column} for column in table.get("columns", []))
                    if kind in (None, "index"):
                        objects.extend({"kind": "index", "schema": schema.get("name"), "table": table.get("name"), **index} for index in table.get("indexes", []))
    return {"snapshot_id": snapshot.id, "captured_at": snapshot.captured_at, "objects": objects}


@app.get("/api/metadata/{snapshot_id}/export.xlsx")
def export_metadata(snapshot_id: int, items: str | None = None, session: Session = Depends(get_session), _: User = Depends(require("metadata:read"))):
    snapshot = session.get(SchemaSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "수집된 스키마 정보를 찾을 수 없습니다.")
    selected_items = {item.strip() for item in items.split(",") if item.strip()} if items else None
    content = build_schema_workbook(snapshot.payload, snapshot.captured_at, snapshot.fingerprint, selected_items=selected_items)
    source_name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(snapshot.payload.get("source") or "schema")).strip("_") or "schema"
    filename = f"MetaVault_{source_name}_{snapshot.captured_at:%Y%m%d_%H%M%S}.xlsx"
    fallback = f"metavault_schema_{snapshot.id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/admin/users")
def users(session: Session = Depends(get_session), _: User = Depends(require("users:read"))):
    return [user_out(user) for user in session.scalars(select(User).order_by(User.email)).all()]


@app.post("/api/admin/users", status_code=201)
def create_user(payload: UserIn, session: Session = Depends(get_session), _: User = Depends(require("users:write"))):
    if session.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(409, "이미 등록된 이메일입니다.")
    if not payload.password:
        raise HTTPException(400, "신규 사용자의 비밀번호가 필요합니다.")
    item = User(email=payload.email, name=payload.name, password_hash=hash_password(payload.password), is_active=payload.is_active)
    item.roles = list(session.scalars(select(Role).where(Role.id.in_(payload.role_ids))).all()) if payload.role_ids else []
    session.add(item)
    session.commit()
    return user_out(item)


@app.put("/api/admin/users/{user_id}")
def update_user(user_id: int, payload: UserIn, session: Session = Depends(get_session), _: User = Depends(require("users:write"))):
    item = session.get(User, user_id)
    if not item:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    item.email, item.name, item.is_active = payload.email, payload.name, payload.is_active
    if payload.password:
        item.password_hash = hash_password(payload.password)
    item.roles = list(session.scalars(select(Role).where(Role.id.in_(payload.role_ids))).all()) if payload.role_ids else []
    session.commit()
    return user_out(item)


@app.delete("/api/admin/users/{user_id}", status_code=204)
def delete_user(user_id: int, session: Session = Depends(get_session), _: User = Depends(require("users:write"))):
    item = session.get(User, user_id)
    if not item:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    if item.id == _.id:
        raise HTTPException(400, "자기 자신은 삭제할 수 없습니다.")
    session.delete(item)
    session.commit()


@app.get("/api/admin/roles")
def roles(session: Session = Depends(get_session), _: User = Depends(require("roles:read"))):
    return [{"id": role.id, "name": role.name, "description": role.description, "permissions": [p.id for p in role.permissions], "menus": [m.id for m in role.menus]} for role in session.scalars(select(Role)).all()]


@app.post("/api/admin/roles", status_code=201)
def create_role(payload: RoleIn, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    item = Role(name=payload.name, description=payload.description)
    item.permissions = list(session.scalars(select(Permission).where(Permission.id.in_(payload.permission_ids))).all()) if payload.permission_ids else []
    item.menus = list(session.scalars(select(Menu).where(Menu.id.in_(payload.menu_ids))).all()) if payload.menu_ids else []
    session.add(item)
    session.commit()
    return {"id": item.id}


@app.put("/api/admin/roles/{role_id}")
def update_role(role_id: int, payload: RoleIn, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    item = session.get(Role, role_id)
    if not item:
        raise HTTPException(404, "역할을 찾을 수 없습니다.")
    item.name, item.description = payload.name, payload.description
    item.permissions = list(session.scalars(select(Permission).where(Permission.id.in_(payload.permission_ids))).all()) if payload.permission_ids else []
    item.menus = list(session.scalars(select(Menu).where(Menu.id.in_(payload.menu_ids))).all()) if payload.menu_ids else []
    session.commit()
    return {"id": item.id}


@app.delete("/api/admin/roles/{role_id}", status_code=204)
def delete_role(role_id: int, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    item = session.get(Role, role_id)
    if not item:
        raise HTTPException(404, "역할을 찾을 수 없습니다.")
    if item.name == "시스템 관리자":
        raise HTTPException(400, "기본 시스템 관리자 역할은 삭제할 수 없습니다.")
    session.delete(item)
    session.commit()


@app.get("/api/admin/permissions")
def permissions(session: Session = Depends(get_session), _: User = Depends(require("roles:read"))):
    return session.scalars(select(Permission).order_by(Permission.code)).all()


@app.get("/api/admin/menus")
def menus(session: Session = Depends(get_session), _: User = Depends(require("roles:read"))):
    return session.scalars(select(Menu).order_by(Menu.order)).all()


@app.post("/api/admin/menus", status_code=201)
def create_menu(payload: MenuIn, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    if session.scalar(select(Menu).where(Menu.code == payload.code)):
        raise HTTPException(409, "이미 사용 중인 메뉴 코드입니다.")
    item = Menu(**payload.model_dump())
    session.add(item)
    session.commit()
    return item


@app.put("/api/admin/menus/{menu_id}")
def update_menu(menu_id: int, payload: MenuIn, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    item = session.get(Menu, menu_id)
    if not item:
        raise HTTPException(404, "메뉴를 찾을 수 없습니다.")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    session.commit()
    return item


@app.delete("/api/admin/menus/{menu_id}", status_code=204)
def delete_menu(menu_id: int, session: Session = Depends(get_session), _: User = Depends(require("roles:write"))):
    item = session.get(Menu, menu_id)
    if not item:
        raise HTTPException(404, "메뉴를 찾을 수 없습니다.")
    session.delete(item)
    session.commit()
