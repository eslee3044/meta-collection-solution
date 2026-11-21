import base64
import binascii
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


def _credential_key() -> bytes:
    settings = get_settings()
    # Existing deployments may fall back to the token key, while new
    # deployments can isolate credential encryption with a dedicated key.
    source = settings.credential_encryption_key or settings.secret_key
    raw = hashlib.sha256(source.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _credential_decryption_keys() -> list[bytes]:
    settings = get_settings()
    keys = [_credential_key()]
    if settings.credential_encryption_key:
        legacy = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
        if legacy not in keys:
            keys.append(legacy)
    return keys


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


def encrypt_credentials(value: dict) -> str:
    if not value:
        return ""
    token = Fernet(_credential_key()).encrypt(json.dumps(value).encode()).decode()
    return f"v1:{token}"


def decrypt_credentials(value: str) -> dict:
    if not value:
        return {}
    try:
        version, token = value.split(":", 1)
        if version != "v1":
            raise ValueError("unsupported credential version")
        for key in _credential_decryption_keys():
            try:
                return json.loads(Fernet(key).decrypt(token.encode()))
            except InvalidToken:
                continue
        raise InvalidToken
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="저장된 Datalake 인증 정보를 복호화할 수 없습니다.")


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
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증이 만료되었거나 유효하지 않습니다.")

