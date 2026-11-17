from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

from app import pk_candidate_service as service
from app.schemas import PkCandidate


IDENTITY = {
    "system_cd": "ABC1",
    "instance_name": "db",
    "postfix": "",
    "owner": "public",
    "table_name": "orders",
}


def _external_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE TB_META_TABLES_EXT (
                SYSTEM_CD TEXT, INSTANCE_NAME TEXT, POSTFIX TEXT, OWNER TEXT,
                TABLE_NAME TEXT, SRC_SNAPSHOT_ID INTEGER, SRC_DATA_SOURCE_ID INTEGER
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE TB_META_COLUMNS_EXT (
                SYSTEM_CD TEXT, INSTANCE_NAME TEXT, POSTFIX TEXT, OWNER TEXT,
                TABLE_NAME TEXT, COLUMN_NAME TEXT, COLUMN_ID INTEGER,
                PK_YN TEXT, IS_ACTIVE TEXT, COLUMN_STATUS TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE TB_META_PK_CANDIDATES_EXT (
                CANDIDATE_ID INTEGER PRIMARY KEY, SYSTEM_CD TEXT, INSTANCE_NAME TEXT,
                POSTFIX TEXT, OWNER TEXT, TABLE_NAME TEXT, OBJECT_TYPE TEXT,
                SRC_DATA_SOURCE_ID INTEGER, SRC_SNAPSHOT_ID INTEGER, CANDIDATE_RANK INTEGER,
                CANDIDATE_COLUMNS_JSON TEXT, CANDIDATE_FINGERPRINT TEXT UNIQUE,
                SOURCE_TYPE TEXT, METHOD TEXT, MODEL_NAME TEXT, CONFIDENCE NUMERIC,
                REASON TEXT, STATUS TEXT, VALIDATION_STATUS TEXT, ROW_COUNT INTEGER,
                NULL_COUNT INTEGER, DUPLICATE_GROUP_COUNT INTEGER, VALIDATED_AT TEXT,
                VALIDATION_MESSAGE TEXT, CREATED_BY TEXT, CREATED_AT TEXT,
                REVIEWED_BY TEXT, REVIEWED_AT TEXT, APPLIED_BY TEXT, APPLIED_AT TEXT
            )
        """)
        conn.execute(text("INSERT INTO TB_META_TABLES_EXT VALUES (:s,:i,:p,:o,:t,10,7)"), {**IDENTITY, "s": IDENTITY["system_cd"], "i": IDENTITY["instance_name"], "p": IDENTITY["postfix"], "o": IDENTITY["owner"], "t": IDENTITY["table_name"]})
        for n, cid in (("ORDER_NO", 1), ("LINE_NO", 2), ("AMOUNT", 3)):
            conn.execute(text("INSERT INTO TB_META_COLUMNS_EXT VALUES (:s,:i,:p,:o,:t,:n,:cid,'Y','Y','ACTIVE')"), {**IDENTITY, "s": IDENTITY["system_cd"], "i": IDENTITY["instance_name"], "p": IDENTITY["postfix"], "o": IDENTITY["owner"], "t": IDENTITY["table_name"], "n": n, "cid": cid})
    return engine


def _external_session(engine):
    source = SimpleNamespace(id=7)
    config = SimpleNamespace(source_type="external", external_source_id=7, schema_name=None,
                             tables_table_name="TB_META_TABLES_EXT", columns_table_name="TB_META_COLUMNS_EXT")
    session = Mock()
    session.get.side_effect = lambda model, key: config if getattr(model, "__name__", "") == "MetaTableConfig" else source
    return session, source, config


def test_candidate_response_schema_accepts_persisted_validation_fields():
    candidate = PkCandidate.model_validate({
        "candidate_id": 1,
        "rank": 1,
        "columns": ["ORDER_NO", "LINE_NO"],
        "source_type": "OFFLINE_RULES",
        "method": "offline-rules",
        "model_name": None,
        "confidence": 0.7,
        "reason": "grain",
        "status": "GENERATED",
        "validation_status": "PENDING",
        "row_count": None,
        "null_count": None,
        "duplicate_group_count": None,
        "validation_message": None,
        "src_snapshot_id": 10,
    })
    assert candidate.src_snapshot_id == 10
    assert candidate.row_count is None


def test_external_generate_persists_and_list_returns_candidates(monkeypatch):
    engine = _external_db()
    session, source, config = _external_session(engine)
    monkeypatch.setattr(service, "source_engine", lambda _: engine)
    monkeypatch.setattr(service, "resolve_registered", lambda s, identity: (config, {"SRC_SNAPSHOT_ID": 10, "SRC_DATA_SOURCE_ID": 7}, {"columns": [{"name": "ORDER_NO"}, {"name": "LINE_NO"}]}, "TABLE", source))
    result = service.generate(session, SimpleNamespace(**IDENTITY), "tester", lambda *_: {"candidates": [{"columns": ["ORDER_NO", "LINE_NO"], "confidence": .7, "reason": "grain"}], "fallback_used": True})
    assert result["candidates"][0]["columns"] == ["ORDER_NO", "LINE_NO"]
    listed = service.list_candidates(session, SimpleNamespace(**IDENTITY))
    assert listed["items"][0]["columns"] == ["ORDER_NO", "LINE_NO"]


def test_external_apply_updates_columns_and_competing_candidates(monkeypatch):
    engine = _external_db()
    session, source, config = _external_session(engine)
    monkeypatch.setattr(service, "source_engine", lambda _: engine)
    candidate = {**IDENTITY, "candidate_id": 1, "src_snapshot_id": 10, "validation_status": "PASSED", "status": "VALIDATED", "candidate_columns_json": '["ORDER_NO", "LINE_NO"]'}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO TB_META_PK_CANDIDATES_EXT (CANDIDATE_ID,SYSTEM_CD,INSTANCE_NAME,POSTFIX,OWNER,TABLE_NAME,OBJECT_TYPE,SRC_SNAPSHOT_ID,CANDIDATE_RANK,CANDIDATE_COLUMNS_JSON,CANDIDATE_FINGERPRINT,SOURCE_TYPE,METHOD,CONFIDENCE,STATUS,VALIDATION_STATUS,CREATED_AT) VALUES (1,'ABC1','db','', 'public','orders','TABLE',10,1,'[\"ORDER_NO\",\"LINE_NO\"]','fp1','OFFLINE_RULES','offline-rules',.7,'VALIDATED','PASSED','now')"))
        conn.execute(text("INSERT INTO TB_META_PK_CANDIDATES_EXT (CANDIDATE_ID,SYSTEM_CD,INSTANCE_NAME,POSTFIX,OWNER,TABLE_NAME,OBJECT_TYPE,SRC_SNAPSHOT_ID,CANDIDATE_RANK,CANDIDATE_COLUMNS_JSON,CANDIDATE_FINGERPRINT,SOURCE_TYPE,METHOD,CONFIDENCE,STATUS,VALIDATION_STATUS,CREATED_AT) VALUES (2,'ABC1','db','', 'public','orders','TABLE',10,2,'[\"AMOUNT\"]','fp2','OFFLINE_RULES','offline-rules',.5,'GENERATED','PENDING','now')"))
    monkeypatch.setattr(service, "resolve_registered", lambda s, identity: (config, {"SRC_SNAPSHOT_ID": 10}, {"columns": [{"name": "ORDER_NO"}, {"name": "LINE_NO"}, {"name": "AMOUNT"}]}, "TABLE", source))
    session.get.side_effect = lambda model, key: None if getattr(model, "__name__", "") == "MetaPkCandidate" else (config if getattr(model, "__name__", "") == "MetaTableConfig" else source)
    result = service.apply(session, 1, True, "tester")
    assert result["applied_columns"] == ["ORDER_NO", "LINE_NO"]
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT COLUMN_NAME, PK_YN FROM TB_META_COLUMNS_EXT" )).all())
        assert rows == {"ORDER_NO": "Y", "LINE_NO": "Y", "AMOUNT": "N"}
        assert conn.execute(text("SELECT STATUS FROM TB_META_PK_CANDIDATES_EXT WHERE CANDIDATE_ID=2")).scalar_one() == "REJECTED"


def test_external_reject_does_not_change_column_pk_state(monkeypatch):
    engine = _external_db()
    session, source, config = _external_session(engine)
    monkeypatch.setattr(service, "source_engine", lambda _: engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE TB_META_COLUMNS_EXT SET PK_YN='Y' WHERE COLUMN_NAME='ORDER_NO'"))
        conn.execute(text("INSERT INTO TB_META_PK_CANDIDATES_EXT (CANDIDATE_ID,SYSTEM_CD,INSTANCE_NAME,POSTFIX,OWNER,TABLE_NAME,OBJECT_TYPE,SRC_SNAPSHOT_ID,CANDIDATE_RANK,CANDIDATE_COLUMNS_JSON,CANDIDATE_FINGERPRINT,SOURCE_TYPE,METHOD,CONFIDENCE,STATUS,VALIDATION_STATUS,CREATED_AT) VALUES (1,'ABC1','db','', 'public','orders','TABLE',10,1,'[\"LINE_NO\"]','fp1','OFFLINE_RULES','offline-rules',.7,'GENERATED','PENDING','now')"))
    session.get.side_effect = lambda model, key: None if getattr(model, "__name__", "") == "MetaPkCandidate" else config
    service.reject(session, 1, "not grain", "tester")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT PK_YN FROM TB_META_COLUMNS_EXT WHERE COLUMN_NAME='ORDER_NO'")).scalar_one() == "Y"
