from .config import get_settings


ALL_DB_TYPES = ("postgresql", "mysql", "mariadb", "mssql", "oracle", "sqlite", "db2", "bigquery")
DOCKER_EXCLUDED_DB_TYPES: tuple[str, ...] = ()


def supported_db_types() -> tuple[str, ...]:
    if get_settings().deployment_mode == "docker":
        return tuple(item for item in ALL_DB_TYPES if item not in DOCKER_EXCLUDED_DB_TYPES)
    return ALL_DB_TYPES


def is_supported_db_type(db_type: str) -> bool:
    return db_type in supported_db_types()


def assert_supported_db_type(db_type: str) -> None:
    if not is_supported_db_type(db_type):
        if get_settings().deployment_mode == "docker":
            raise ValueError(f"Docker 배포에서는 {db_type} 수집을 지원하지 않습니다.")
        raise ValueError(f"지원하지 않는 데이터베이스 종류입니다: {db_type}")
