import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import delete_user
from app.models import Permission, Role, User
from app.dependencies import require

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.schema != "EAPET"])
    with Session(engine) as value:
        yield value


def test_admin_can_delete_another_user(session):
    actor = User(email="admin@example.com", name="관리자", password_hash="hash")
    target = User(email="member@example.com", name="회원", password_hash="hash")
    session.add_all([actor, target])
    session.commit()

    delete_user(target.id, session, actor)

    assert session.get(User, target.id) is None


def test_admin_cannot_delete_themselves(session):
    actor = User(email="admin@example.com", name="관리자", password_hash="hash")
    session.add(actor)
    session.commit()

    with pytest.raises(HTTPException) as error:
        delete_user(actor.id, session, actor)

    assert error.value.status_code == 400
    assert "자기 자신" in error.value.detail


def test_admin_wildcard_permission_is_required_for_meta_config():
    permission = Permission(code="admin:*", description="전체 관리자 권한")
    role = Role(name="시스템 관리자", permissions=[permission])
    user = User(email="admin@example.com", name="관리자", password_hash="hash", roles=[role])

    assert require("admin:*")(user) is user

    user.roles = []
    with pytest.raises(HTTPException) as error:
        require("admin:*")(user)
    assert error.value.status_code == 403
