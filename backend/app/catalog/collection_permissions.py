"""Read-only checks for catalog objects required by a collection job."""

from collections import OrderedDict
from typing import Any

from sqlalchemy import text

from ..collector import normalize_collection_items, source_engine
from ..models import CollectionJob, DataSource


CATALOG_OBJECTS: dict[str, dict[str, tuple[str, str]]] = {
    "mysql": {
        "TABLE": ("information_schema.TABLES", "테이블·뷰 목록"),
        "VIEW": ("information_schema.TABLES", "테이블·뷰 목록"),
        "COLUMN": ("information_schema.COLUMNS", "컬럼 목록"),
        "PROCEDURE": ("information_schema.ROUTINES", "프로시저·함수 목록"),
        "INDEX": ("information_schema.STATISTICS", "인덱스 목록"),
        "SELECT PRIVILEGE": ("information_schema.TABLE_PRIVILEGES", "테이블 조회권한"),
        "TRIGGER": ("information_schema.TRIGGERS", "트리거 목록"),
    },
    "mariadb": {
        "TABLE": ("information_schema.TABLES", "테이블·뷰 목록"),
        "VIEW": ("information_schema.TABLES", "테이블·뷰 목록"),
        "COLUMN": ("information_schema.COLUMNS", "컬럼 목록"),
        "PROCEDURE": ("information_schema.ROUTINES", "프로시저·함수 목록"),
        "INDEX": ("information_schema.STATISTICS", "인덱스 목록"),
        "SELECT PRIVILEGE": ("information_schema.TABLE_PRIVILEGES", "테이블 조회권한"),
        "TRIGGER": ("information_schema.TRIGGERS", "트리거 목록"),
    },
    "postgresql": {
        "TABLE": ("information_schema.tables", "테이블·뷰 목록"),
        "VIEW": ("information_schema.tables", "테이블·뷰 목록"),
        "COLUMN": ("information_schema.columns", "컬럼 목록"),
        "PROCEDURE": ("information_schema.routines", "프로시저·함수 목록"),
        "INDEX": ("pg_catalog.pg_indexes", "인덱스 목록"),
        "SELECT PRIVILEGE": ("information_schema.table_privileges", "테이블 조회권한"),
        "TRIGGER": ("information_schema.triggers", "트리거 목록"),
    },
    "mssql": {
        "TABLE": ("INFORMATION_SCHEMA.TABLES", "테이블·뷰 목록"),
        "VIEW": ("INFORMATION_SCHEMA.TABLES", "테이블·뷰 목록"),
        "COLUMN": ("INFORMATION_SCHEMA.COLUMNS", "컬럼 목록"),
        "PROCEDURE": ("INFORMATION_SCHEMA.ROUTINES", "프로시저·함수 목록"),
        "INDEX": ("sys.indexes", "인덱스 목록"),
        "SELECT PRIVILEGE": ("sys.database_permissions", "테이블 조회권한"),
        "TRIGGER": ("sys.triggers", "트리거 목록"),
    },
    "oracle": {
        "TABLE": ("ALL_TABLES", "테이블 목록"),
        "VIEW": ("ALL_VIEWS", "뷰 목록"),
        "COLUMN": ("ALL_TAB_COLUMNS", "컬럼 목록"),
        "PROCEDURE": ("ALL_PROCEDURES", "프로시저·함수 목록"),
        "INDEX": ("ALL_INDEXES", "인덱스 목록"),
        "SELECT PRIVILEGE": ("ALL_TAB_PRIVS", "테이블 조회권한"),
        "TRIGGER": ("ALL_TRIGGERS", "트리거 목록"),
    },
    "db2": {
        "TABLE": ("SYSCAT.TABLES", "테이블·뷰 목록"),
        "VIEW": ("SYSCAT.TABLES", "테이블·뷰 목록"),
        "COLUMN": ("SYSCAT.COLUMNS", "컬럼 목록"),
        "PROCEDURE": ("SYSCAT.ROUTINES", "프로시저·함수 목록"),
        "INDEX": ("SYSCAT.INDEXES", "인덱스 목록"),
        "SELECT PRIVILEGE": ("SYSCAT.TABAUTH", "테이블 조회권한"),
        "TRIGGER": ("SYSCAT.TRIGGERS", "트리거 목록"),
    },
    "vertica": {
        "TABLE": ("v_catalog.tables", "테이블 목록"),
        "VIEW": ("v_catalog.views", "뷰 목록"),
        "COLUMN": ("v_catalog.columns", "컬럼 목록"),
        "PROCEDURE": ("v_catalog.procedures", "프로시저 목록"),
        "INDEX": ("v_catalog.projections", "projection 목록"),
        "SELECT PRIVILEGE": ("v_catalog.grants", "테이블 조회권한"),
    },
    "sqlite": {
        "TABLE": ("sqlite_master", "테이블·뷰 목록"),
        "VIEW": ("sqlite_master", "테이블·뷰 목록"),
        "COLUMN": ("sqlite_master", "컬럼 목록"),
    },
}


def _requirements(source: DataSource, collection_items: list[str]) -> list[dict[str, Any]]:
    mapping = CATALOG_OBJECTS.get(source.db_type)
    if not mapping:
        names = [
            ("information_schema.TABLES", "테이블·뷰 목록"),
            ("information_schema.COLUMNS", "컬럼 목록"),
            ("information_schema.ROUTINES", "프로시저·함수 목록"),
        ]
        return [{"object_name": name, "purpose": purpose, "required_for": list(collection_items)} for name, purpose in names]
    unique: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for item in collection_items:
        if item in mapping:
            object_name, purpose = mapping[item]
            row = unique.setdefault(object_name, {"object_name": object_name, "purpose": purpose, "required_for": []})
            row["required_for"].append(item)
    return list(unique.values())


def _unknown_result(source: DataSource, requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        **requirement,
        "status": "unknown",
        "reason": "이 DB는 catalog 접근권한이 IAM/DB 관리자 정책으로 결정되므로 일반 SQL로 확정할 수 없습니다.",
        "request_hint": f"{requirement['object_name']} 조회권한과 대상 스키마 권한을 수집 계정에 부여해 주세요.",
    }


def check_collection_catalog_permissions(source: DataSource, job: CollectionJob) -> dict[str, Any]:
    requirements = _requirements(source, normalize_collection_items(list(job.collection_items or [])))
    selected_schemas = list(job.schemas or [])
    base = {
        "job_id": job.id,
        "job_name": job.name,
        "source": source.name,
        "db_type": source.db_type,
        "database": source.database,
        "schemas": selected_schemas,
        "requirements": [],
    }
    if not requirements:
        return {**base, "status": "complete", "summary": {"allowed": 0, "denied": 0, "unknown": 0, "error": 0}}
    if source.db_type == "bigquery":
        checked = [_unknown_result(source, requirement) for requirement in requirements]
        return {**base, "status": "partial", "requirements": checked, "summary": {"allowed": 0, "denied": 0, "unknown": len(checked), "error": 0}}

    checked: list[dict[str, Any]] = []
    try:
        with source_engine(source) as engine:
            with engine.connect() as connection:
                for requirement in requirements:
                    try:
                        connection.execute(text(f"SELECT 1 FROM {requirement['object_name']} WHERE 1 = 0"))
                        checked.append({**requirement, "status": "allowed", "reason": "catalog object SELECT 확인 성공", "request_hint": None})
                    except Exception as exc:
                        checked.append({**requirement, "status": "denied", "reason": str(exc)[:300], "request_hint": f"{requirement['object_name']}에 SELECT 권한을 수집 계정에 부여해 주세요."})
    except Exception as exc:
        checked = [{**requirement, "status": "error", "reason": f"DB 연결 실패: {str(exc)[:300]}", "request_hint": "DB 접속정보와 네트워크·인증정보를 확인해 주세요."} for requirement in requirements]

    summary = {status: sum(item["status"] == status for item in checked) for status in ("allowed", "denied", "unknown", "error")}
    status = "complete" if not summary["denied"] and not summary["unknown"] and not summary["error"] else "partial"
    return {**base, "status": status, "requirements": checked, "summary": summary}
