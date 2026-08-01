from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_session
from .dependencies import current_user, require
from .models import CollectionJob, CollectionRun, DataSource, Menu, Permission, Role, SchemaSnapshot, User
from .collector import test_source
from .scheduler import execute_job, start_scheduler, stop_scheduler, sync_jobs
from .schemas import DataSourceIn, DataSourceOut, JobIn, JobOut, LoginRequest, LoginResponse, MenuIn, RoleIn, RunOut, UserIn, UserOut
from .security import create_token, encrypt_json, hash_password, verify_password
from .seed import seed


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, name=user.name, is_active=user.is_active,
        roles=[role.name for role in user.roles],
        permissions=sorted({p.code for role in user.roles for p in role.permissions}),
        menus=[menu.code for role in user.roles for menu in role.menus],
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
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


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    return LoginResponse(access_token=create_token(user.id), user=user_out(user))


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


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
    for field in ["name", "db_type", "host", "port", "database", "username", "options", "ssh_enabled", "ssh_host", "ssh_port", "ssh_username", "ssh_auth_type"]:
        setattr(item, field, getattr(payload, field))
    if payload.password is not None:
        item.secret_encrypted = encrypt_json({"password": payload.password})
    if payload.ssh_password is not None or payload.ssh_private_key is not None:
        item.ssh_secret_encrypted = encrypt_json({
            "password": payload.ssh_password,
            "private_key": payload.ssh_private_key,
            "private_key_passphrase": payload.ssh_private_key_passphrase,
        })


@app.get("/api/sources", response_model=list[DataSourceOut])
def list_sources(session: Session = Depends(get_session), _: User = Depends(require("sources:read"))):
    return session.scalars(select(DataSource).order_by(DataSource.name)).all()


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


@app.post("/api/jobs", response_model=JobOut, status_code=201)
def create_job(payload: JobIn, session: Session = Depends(get_session), _: User = Depends(require("jobs:write"))):
    if not session.get(DataSource, payload.data_source_id):
        raise HTTPException(400, "데이터 소스를 찾을 수 없습니다.")
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
    if not session.get(CollectionJob, job_id):
        raise HTTPException(404, "수집 작업을 찾을 수 없습니다.")
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


@app.get("/api/metadata")
def metadata(session: Session = Depends(get_session), _: User = Depends(require("metadata:read"))):
    snapshots = session.scalars(select(SchemaSnapshot).order_by(desc(SchemaSnapshot.captured_at))).all()
    seen, result = set(), []
    for item in snapshots:
        if item.data_source_id not in seen:
            result.append({"id": item.id, "data_source_id": item.data_source_id, "run_id": item.run_id, "captured_at": item.captured_at, "fingerprint": item.fingerprint, "payload": item.payload})
            seen.add(item.data_source_id)
    return result


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
