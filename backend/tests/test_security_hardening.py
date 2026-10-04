import pytest
from contextlib import asynccontextmanager
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.security import decode_token


def test_docker_settings_reject_insecure_bootstrap_values():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            deployment_mode="docker",
            secret_key="change-this-before-production",
            admin_password="safe-password-123",
        )

    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(
            deployment_mode="docker",
            secret_key="s" * 48,
            admin_password="Admin123!",
        )


def test_docker_settings_reject_wildcard_cors():
    with pytest.raises(ValueError, match="CORS"):
        Settings(
            deployment_mode="docker",
            secret_key="s" * 48,
            admin_password="safe-password-123",
            cors_origins="*",
        )


def test_malformed_token_is_a_normal_unauthorized_error():
    with pytest.raises(HTTPException) as error:
        decode_token("not-base64.%%%")

    assert error.value.status_code == 401


def test_api_emits_security_headers():
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def no_op_lifespan(_app):
        yield

    app.router.lifespan_context = no_op_lifespan
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
    finally:
        app.router.lifespan_context = original_lifespan

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
