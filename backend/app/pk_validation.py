"""Count-only validation of logical primary-key candidates against a source object."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from .collector import source_engine
from .models import DataSource


PASSED = "PASSED"
FAILED = "FAILED"
EMPTY_SOURCE = "EMPTY_SOURCE"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ValidationResult:
    status: str
    row_count: int | None = None
    null_count: int | None = None
    duplicate_group_count: int | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "validation_status": self.status,
            "row_count": self.row_count,
            "null_count": self.null_count,
            "duplicate_group_count": self.duplicate_group_count,
            "message": self.message,
        }


def _objects(payload: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any], str]]:
    result = []
    for schema in payload.get("schemas", []) or []:
        schema_name = str(schema.get("name") or "")
        for kind, object_type in (("tables", "TABLE"), ("views", "VIEW")):
            for item in schema.get(kind, []) or []:
                if isinstance(item, Mapping) and item.get("name") is not None:
                    result.append((schema_name, item, object_type))
    return result


def resolve_snapshot_object(
    snapshot_payload: Mapping[str, Any], object_name: str
) -> tuple[str, Mapping[str, Any], str] | None:
    """Resolve only an object present in the current snapshot (table or view)."""
    matches = [item for item in _objects(snapshot_payload) if item[1].get("name") == object_name]
    return matches[0] if len(matches) == 1 else None


def _quoted_target(connection: Connection, schema_name: str, object_name: str) -> str:
    preparer = connection.dialect.identifier_preparer
    quoted_object = preparer.quote(object_name)
    return f"{preparer.quote_schema(schema_name)}.{quoted_object}" if schema_name else quoted_object


def _quoted_columns(connection: Connection, columns: Sequence[str]) -> list[str]:
    return [connection.dialect.identifier_preparer.quote(column) for column in columns]


def _connection_context(factory: Callable[[DataSource], Any], source: DataSource):
    resource = factory(source)
    # source_engine is a context manager; this also makes the service easy to test
    # with an already-created SQLAlchemy Engine.
    return resource if hasattr(resource, "__enter__") else nullcontext(resource)


def _unavailable() -> ValidationResult:
    # Do not expose driver errors: they can contain credentials, URLs, SQL, or row data.
    return ValidationResult(UNAVAILABLE, message="원천 데이터에 접근할 수 없어 검증할 수 없습니다.")


def validate_source_data(
    source: DataSource,
    snapshot_payload: Mapping[str, Any],
    object_name: str,
    candidate_columns: Sequence[str],
    *,
    engine_factory: Callable[[DataSource], Any] | None = None,
    duplicate_limit: int = 1000,
) -> ValidationResult:
    """Validate a candidate using aggregate queries only.

    ``snapshot_payload`` is the allowlist. No identifier supplied by a caller is
    placed into SQL until it has matched the current snapshot object and columns.
    ``duplicate_limit`` bounds work and result transfer for large sources.
    """
    if not isinstance(object_name, str) or not object_name or not candidate_columns:
        return ValidationResult(FAILED, message="검증 대상 또는 후보 컬럼이 올바르지 않습니다.")
    columns = list(candidate_columns)
    if len(set(columns)) != len(columns) or any(not isinstance(column, str) or not column for column in columns):
        return ValidationResult(FAILED, message="후보 컬럼이 현재 스냅샷과 일치하지 않습니다.")
    resolved = resolve_snapshot_object(snapshot_payload, object_name)
    if resolved is None:
        return ValidationResult(FAILED, message="후보가 현재 스냅샷과 달라 검증할 수 없습니다.")
    schema_name, snapshot_object, _object_type = resolved
    allowed = {
        str(column.get("name"))
        for column in snapshot_object.get("columns", []) or []
        if isinstance(column, Mapping) and column.get("name") is not None
    }
    if any(column not in allowed for column in columns):
        return ValidationResult(FAILED, message="후보 컬럼이 현재 스냅샷과 달라 검증할 수 없습니다.")
    if not isinstance(duplicate_limit, int) or duplicate_limit < 1:
        duplicate_limit = 1000

    try:
        factory = engine_factory or source_engine
        with _connection_context(factory, source) as engine:
            with engine.connect() as connection:
                target = _quoted_target(connection, schema_name, object_name)
                quoted_columns = _quoted_columns(connection, columns)
                row_count = int(connection.execute(text(f"SELECT COUNT(*) FROM {target}")).scalar_one())
                if row_count == 0:
                    return ValidationResult(EMPTY_SOURCE, row_count=0, null_count=0, duplicate_group_count=0,
                                            message="데이터가 없어 유일성을 검증할 수 없습니다.")
                null_predicate = " OR ".join(f"{column} IS NULL" for column in quoted_columns)
                null_count = int(connection.execute(text(f"SELECT COUNT(*) FROM {target} WHERE {null_predicate}")).scalar_one())
                grouped = ", ".join(quoted_columns)
                duplicate_sql = (
                    f"SELECT COUNT(*) FROM (SELECT {grouped} FROM {target} "
                    f"GROUP BY {grouped} HAVING COUNT(*) > 1 LIMIT :duplicate_limit) AS duplicate_groups"
                )
                duplicate_count = int(connection.execute(text(duplicate_sql), {"duplicate_limit": duplicate_limit}).scalar_one())
    except Exception:
        return _unavailable()

    if null_count or duplicate_count:
        return ValidationResult(
            FAILED, row_count=row_count, null_count=null_count, duplicate_group_count=duplicate_count,
            message="후보 컬럼에 NULL 또는 중복이 있어 논리 PK로 적용할 수 없습니다.",
        )
    return ValidationResult(
        PASSED, row_count=row_count, null_count=0, duplicate_group_count=0,
        message="NULL과 중복이 없어 논리 PK로 적용할 수 있습니다.",
    )


# Service-friendly name; kept as a small alias so callers need not know the SQL detail.
validate_candidate = validate_source_data
