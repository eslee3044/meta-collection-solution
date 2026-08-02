from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_session
from .models import User
from .security import decode_token


def current_user(authorization: str | None = Header(default=None), session: Session = Depends(get_session)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    user = session.get(User, decode_token(authorization[7:]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용할 수 없는 계정입니다.")
    return user


def require(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        codes = {item.code for role in user.roles for item in role.permissions}
        if "admin:*" not in codes and permission not in codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한이 없습니다.")
        return user
    return dependency

