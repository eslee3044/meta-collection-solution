from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.datalake_target_service import sync_meta_target_database, sync_meta_target_database_from_active_target
from app.models import DatalakeTarget, MetaTableConfig


def test_sync_meta_target_database_preserves_other_meta_settings():
    engine = create_engine("sqlite:///:memory:")
    cast(Any, MetaTableConfig.__table__).create(engine)

    with Session(engine) as session:
        session.add(
            MetaTableConfig(
                id=1,
                source_type="internal",
                schema_name="CUSTOM_META",
                tables_table_name="CUSTOM_TABLES",
                columns_table_name="CUSTOM_COLUMNS",
                target_database_name="BigQuery",
                description_ai_enabled=True,
                description_ai_provider="ollama",
                description_ai_model="custom-model",
            )
        )
        session.commit()

        result = sync_meta_target_database(session, "postgresql")
        session.commit()
        saved = session.get(MetaTableConfig, 1)

        assert result == "PostgreSQL"
        assert saved is not None
        assert saved.target_database_name == "PostgreSQL"
        assert saved.schema_name == "CUSTOM_META"
        assert saved.tables_table_name == "CUSTOM_TABLES"
        assert saved.columns_table_name == "CUSTOM_COLUMNS"
        assert saved.description_ai_enabled is True
        assert saved.description_ai_provider == "ollama"
        assert saved.description_ai_model == "custom-model"


def test_sync_meta_target_database_rejects_unsupported_target():
    engine = create_engine("sqlite:///:memory:")
    cast(Any, MetaTableConfig.__table__).create(engine)

    with Session(engine) as session, pytest.raises(HTTPException) as error:
        sync_meta_target_database(session, "unknown")

    assert error.value.status_code == 400
    assert "지원하지 않는" in str(error.value.detail)


def test_active_datalake_target_overrides_meta_registration_default():
    engine = create_engine("sqlite:///:memory:")
    cast(Any, MetaTableConfig.__table__).create(engine)
    cast(Any, DatalakeTarget.__table__).create(engine)

    with Session(engine) as session:
        session.add(MetaTableConfig(id=1, target_database_name="BigQuery"))
        session.add(DatalakeTarget(id=1, target_type="postgresql", secret_encrypted="encrypted", is_active=True))
        session.commit()

        result = sync_meta_target_database_from_active_target(session)
        session.commit()

        saved = session.get(MetaTableConfig, 1)
        assert result == "PostgreSQL"
        assert saved is not None
        assert saved.target_database_name == "PostgreSQL"
