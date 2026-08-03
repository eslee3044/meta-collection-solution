import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import delete_user
from app.models import User


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
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
