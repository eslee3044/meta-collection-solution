from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Menu, Permission, Role, User
from .security import hash_password, verify_password


PERMISSIONS = {
    "admin:*": "전체 관리자 권한",
    "sources:read": "데이터 소스 조회",
    "sources:write": "데이터 소스 관리",
    "jobs:read": "수집 작업 조회",
    "jobs:write": "수집 작업 관리 및 실행",
    "metadata:read": "스키마 메타데이터 조회",
    "users:read": "사용자 조회",
    "users:write": "사용자 관리",
    "roles:read": "역할과 메뉴 조회",
    "roles:write": "역할과 메뉴 관리",
}
MENUS = [
    ("dashboard", "대시보드", "/", "LayoutDashboard", 1),
    ("sources", "DB 접속 관리", "/sources", "Database", 2),
    ("metadata", "스키마 정보", "/metadata", "TableProperties", 3),
    ("jobs", "수집 스케줄", "/jobs", "CalendarClock", 4),
    ("users", "사용자 관리", "/users", "Users", 5),
    ("roles", "역할 및 권한", "/roles", "ShieldCheck", 6),
]


def seed(session: Session) -> None:
    permissions = {}
    for code, description in PERMISSIONS.items():
        item = session.scalar(select(Permission).where(Permission.code == code)) or Permission(code=code, description=description)
        session.add(item)
        permissions[code] = item
    menus = []
    for code, label, path, icon, order in MENUS:
        item = session.scalar(select(Menu).where(Menu.code == code)) or Menu(code=code, label=label, path=path, icon=icon, order=order)
        session.add(item)
        menus.append(item)
    session.flush()
    role = session.scalar(select(Role).where(Role.name == "시스템 관리자"))
    if not role:
        role = Role(name="시스템 관리자", description="모든 기능을 관리하는 기본 역할")
        session.add(role)
    role.permissions = [permissions["admin:*"]]
    role.menus = menus
    settings = get_settings()
    user = session.scalar(select(User).where(User.email == settings.admin_email))
    if not user:
        user = User(email=settings.admin_email, name="관리자", password_hash=hash_password(settings.admin_password), roles=[role])
        session.add(user)
    elif not verify_password(settings.admin_password, user.password_hash):
        # The configured bootstrap password is the recovery path for the local/admin account.
        # Keep existing accounts untouched; only reconcile this designated admin identity.
        user.password_hash = hash_password(settings.admin_password)
        user.is_active = True
        user.roles = [role]
    session.commit()

