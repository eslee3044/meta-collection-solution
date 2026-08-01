import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from .config import get_settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _key() -> bytes:
    raw = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_json(value: dict) -> str:
    if not value:
        return ""
    return Fernet(_key()).encrypt(json.dumps(value).encode()).decode()


def decrypt_json(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(Fernet(_key()).decrypt(value.encode()))
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="저장된 인증 정보를 복호화할 수 없습니다.")


def create_token(user_id: int) -> str:
    settings = get_settings()
    payload = {"sub": user_id, "exp": int((datetime.now(timezone.utc) + timedelta(minutes=settings.token_minutes)).timestamp())}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def decode_token(token: str) -> int:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["exp"] < datetime.now(timezone.utc).timestamp():
            raise ValueError
        return int(payload["sub"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증이 만료되었거나 유효하지 않습니다.")

