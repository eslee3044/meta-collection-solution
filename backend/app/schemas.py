from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    is_active: bool
    roles: list[str] = []
    permissions: list[str] = []
    menus: list[str] = []


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DataSourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    db_type: Literal["postgresql", "mysql", "mariadb", "mssql", "oracle", "sqlite", "db2", "bigquery"]
    host: str = "localhost"
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str | None = None
    service_account_json: str | None = None
    options: dict[str, Any] = {}
    ssl_enabled: bool = False
    ssl_ca_cert: str | None = None
    ssl_cert: str | None = None
    ssl_key: str | None = None
    ssh_enabled: bool = False
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_username: str | None = None
    ssh_auth_type: Literal["password", "private_key"] | None = None
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    ssh_private_key_passphrase: str | None = None


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    db_type: str
    host: str
    port: int | None
    database: str
    username: str
    options: dict[str, Any]
    ssh_enabled: bool
    ssh_host: str | None
    ssh_port: int
    ssh_username: str | None
    ssh_auth_type: str | None
    status: str
    last_tested_at: datetime | None
    created_at: datetime


class JobIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    data_source_id: int
    schedule_type: Literal["cron", "interval", "manual"] = "cron"
    cron: str = "0 2 * * *"
    interval_minutes: int | None = Field(default=None, ge=1)
    schemas: list[str] = []
    collection_items: list[str] = Field(default_factory=lambda: ["INDEX", "TABLE", "VIEW", "PROCEDURE", "SELECT PRIVILEGE"])
    collect_storage: bool = False
    is_active: bool = True


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    data_source_id: int
    schedule_type: str
    cron: str
    interval_minutes: int | None
    schemas: list[str]
    collection_items: list[str]
    collect_storage: bool
    is_active: bool
    next_run_at: datetime | None
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    object_count: int
    error_message: str | None


class RunLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    sequence: int
    level: str
    step: str
    message: str
    details: str | None
    created_at: datetime


class UserIn(BaseModel):
    email: str
    name: str
    password: str | None = None
    is_active: bool = True
    role_ids: list[int] = []


class RoleIn(BaseModel):
    name: str
    description: str = ""
    permission_ids: list[int] = []
    menu_ids: list[int] = []


class MetaTableConfigIn(BaseModel):
    source_type: Literal["internal", "external"] = "internal"
    external_source_id: int | None = None
    schema_name: str = Field(default="EAPET", min_length=1, max_length=255)
    tables_table_name: str = Field(default="TB_META_TABLES_EXT", min_length=1, max_length=255)
    columns_table_name: str = Field(default="TB_META_COLUMNS_EXT", min_length=1, max_length=255)


class MetaTableConfigOut(MetaTableConfigIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime


class MetaRegisterIn(BaseModel):
    snapshot_id: int
    table_names: list[str] = Field(min_length=1)
    system_cd: str = Field(min_length=1, max_length=32)
    postfix: str = Field(min_length=1, max_length=32)
    etl_conn_div_cd: str = Field(min_length=1, max_length=32)
    etl_conn_nm: str = Field(min_length=1, max_length=255)
    tgt_ds_cd: str = Field(min_length=1, max_length=255)
    tgt_database_name: str = Field(min_length=1, max_length=255)
    instance_div_cd: str = Field(default="", max_length=32)
    target_name_suffix: str = Field(default="", max_length=32)


class MenuIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=200)
    icon: str = "Circle"
    order: int = 0
    parent_id: int | None = None
