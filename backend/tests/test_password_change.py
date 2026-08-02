import pytest
from fastapi import HTTPException

from app.main import change_password
from app.models import User
from app.schemas import PasswordChangeIn
from app.security import hash_password, verify_password


class FakeSession:
    committed = False

    def commit(self):
        self.committed = True


def test_change_password_requires_current_password_and_updates_hash():
    user = User(email="user@example.com", name="User", password_hash=hash_password("OldPassword1!"), is_active=True)
    session = FakeSession()

    result = change_password(
        PasswordChangeIn(current_password="OldPassword1!", new_password="NewPassword2!"),
        session=session,
        user=user,
    )

    assert result == {"status": "changed"}
    assert session.committed
    assert verify_password("NewPassword2!", user.password_hash)
    assert not verify_password("OldPassword1!", user.password_hash)


def test_change_password_rejects_wrong_or_reused_password():
    user = User(email="user@example.com", name="User", password_hash=hash_password("OldPassword1!"), is_active=True)

    with pytest.raises(HTTPException, match="현재 비밀번호"):
        change_password(PasswordChangeIn(current_password="WrongPassword", new_password="NewPassword2!"), session=FakeSession(), user=user)

    with pytest.raises(HTTPException, match="달라야"):
        change_password(PasswordChangeIn(current_password="OldPassword1!", new_password="OldPassword1!"), session=FakeSession(), user=user)
