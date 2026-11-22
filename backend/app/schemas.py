from datetime import datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    db_type: Literal["postgresql", "mysql", "mariadb", "mssql", "oracle", "sqlite", "db2", "bigquery", "vertica"]
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
    current_step: str
    current_schema: str | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    cancelled_at: datetime | None
    error_code: str | None
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
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


class FullLoadIn(BaseModel):
    job_id: int
    schema_name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    source_schema_name: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    table_name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    key_columns: list[str] = Field(min_length=1)
    batch_id: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    chunk_size: int = Field(default=5000, ge=1, le=100000)


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


class DescriptionColumnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column_name: str = Field(min_length=1, max_length=255)
    data_type: str = Field(default="", max_length=120)
    comments: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=2000)
    nullable: bool | None = None
    null_yn: str | None = Field(default=None, max_length=1)
    pk_yn: str | None = Field(default=None, max_length=1)
    index_yn: str | None = Field(default=None, max_length=1)
    index_names: list[str] = Field(default_factory=list, max_length=30)
    ordinal_position: int | None = None


class DescriptionTableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_name: str = Field(min_length=1, max_length=255)
    comments: str | None = Field(default=None, max_length=4000)
    columns: list[DescriptionColumnIn] = Field(default_factory=list, max_length=500)


class DescriptionPreviewIn(BaseModel):
    table: DescriptionTableIn | None = None
    columns: list[DescriptionColumnIn] = Field(default_factory=list, max_length=500)


class DateColumnRecommendationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_name: str = Field(default="", max_length=255)
    columns: list[DescriptionColumnIn] = Field(default_factory=list, max_length=500)


class ManualAiPromptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_cd: str = Field(default="", max_length=32)
    instance_name: str = Field(default="", max_length=255)
    postfix: str = Field(default="", max_length=32)
    owner: str = Field(default="", max_length=255)
    table_name: str = Field(min_length=1, max_length=255)
    object_type: Literal["TABLE", "VIEW"] = "TABLE"
    snapshot_id: int | None = None
    comments: str | None = Field(default=None, max_length=4000)
    columns: list[DescriptionColumnIn] = Field(default_factory=list, min_length=1, max_length=500)


class ManualAiResponseIn(ManualAiPromptIn):
    response_text: str = Field(min_length=1, max_length=204_800)


class ManualAiApplyIn(ManualAiResponseIn):
    selected_pk_indexes: list[int] = Field(default_factory=list, max_length=4)


class DatalakeTargetConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["postgresql", "bigquery", "redshift"] = "postgresql"
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=512)
    ssl_mode: Literal["disable", "prefer", "require"] = "prefer"
    connect_timeout: int = Field(default=5, ge=1, le=30)
    project_id: str | None = Field(default=None, max_length=255)
    dataset: str | None = Field(default=None, max_length=1024)
    location: str | None = Field(default=None, max_length=120)
    service_account_json: str | None = Field(default=None, max_length=131_072)

    @model_validator(mode="after")
    def validate_target_fields(self):
        if self.target_type in {"postgresql", "redshift"}:
            missing = [name for name in ("host", "database", "username", "password") if not getattr(self, name)]
            if missing:
                raise ValueError(f"{self.target_type} 접속정보 필수값이 없습니다: {', '.join(missing)}")
            if self.port is None:
                self.port = 5439 if self.target_type == "redshift" else 5432
            return self
        missing = [name for name in ("project_id", "dataset", "service_account_json") if not getattr(self, name)]
        if missing:
            raise ValueError(f"BigQuery 접속정보 필수값이 없습니다: {', '.join(missing)}")
        try:
            credentials = json.loads(self.service_account_json or "")
        except json.JSONDecodeError as exc:
            raise ValueError("BigQuery 서비스 계정 JSON 형식이 올바르지 않습니다.") from exc
        required = ("project_id", "private_key", "client_email", "token_uri")
        if not isinstance(credentials, dict) or any(not credentials.get(name) for name in required):
            raise ValueError("BigQuery 서비스 계정 JSON에 필수 인증 항목이 없습니다.")
        return self


class DatalakeTargetReplaceIn(DatalakeTargetConnectionIn):
    confirm_replace: Literal[True]


class DatalakeTargetOut(BaseModel):
    configured: bool
    target_type: str | None = None
    status: str
    credential_configured: bool
    connection_summary: dict[str, Any] = Field(default_factory=dict)
    dedicated_encryption_key: bool
    last_tested_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MetaTableConfigIn(BaseModel):
    source_type: Literal["internal", "external"] = "internal"
    external_source_id: int | None = None
    schema_name: str = Field(default="EAPET", min_length=1, max_length=255)
    tables_table_name: str = Field(default="TB_META_TABLES_EXT", min_length=1, max_length=255)
    columns_table_name: str = Field(default="TB_META_COLUMNS_EXT", min_length=1, max_length=255)
    target_database_name: str = Field(default="PostgreSQL", min_length=1, max_length=255)
    description_ai_enabled: bool = False
    description_ai_provider: Literal["rules", "ollama", "manual"] = "rules"
    description_ai_model: str = Field(default="qwen3:latest", min_length=1, max_length=120)


class MetaTableConfigOut(MetaTableConfigIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime


class MetaRegisterIn(BaseModel):
    snapshot_id: int
    table_names: list[str] = Field(min_length=1)
    system_cd: str = Field(pattern=r"^[A-Z][A-Z0-9]{2}[A-Z0-9_]$")
    postfix: str = Field(default="", pattern=r"^[A-Za-z0-9_]*$", max_length=32)
    etl_conn_div_cd: Literal["Oracle", "ODBC"]
    etl_conn_nm: str = Field(min_length=1, max_length=255)
    tgt_ds_cd: str = Field(pattern=r"^ST_[A-Z][A-Z0-9]{2}[A-Z0-9_]$")
    tgt_database_name: str = Field(default="PostgreSQL", min_length=1, max_length=255)
    instance_div_cd: str = Field(default="", max_length=32)
    target_name_suffix: str = Field(default="", max_length=32)
    columns_by_table: dict[str, list[str]] | None = None
    date_recommendations: dict[str, dict[str, list[str]]] | None = None
    table_comments: dict[str, str] | None = None


class MenuIn(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=200)
    icon: str = "Circle"
    order: int = 0
    parent_id: int | None = None


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisteredTableIdentity(StrictSchema):
    system_cd: str = Field(min_length=1, max_length=32)
    instance_name: str = Field(min_length=1, max_length=255)
    postfix: str = Field(default="", max_length=32)
    owner: str = Field(min_length=1, max_length=255)
    table_name: str = Field(min_length=1, max_length=255)


class RegisteredProcedureApplyIn(RegisteredTableIdentity):
    ddl_sql: str | None = Field(default=None, max_length=100000)


class RegisteredDatalakePlanApplyIn(RegisteredTableIdentity):
    spec_fingerprint: str = Field(min_length=64, max_length=64)
    ddl_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    acknowledgements: list[str] = Field(default_factory=list)


class SourceRuntimePrepareIn(RegisteredTableIdentity):
    pool_slots: int = Field(default=2, ge=1, le=32)
    confirm_pool_resize: bool = False
    credential_mode: Literal["metadata", "dedicated"] = "metadata"
    dedicated_username: str | None = Field(default=None, max_length=255)
    dedicated_password: str | None = Field(default=None, max_length=512)


class LoadPlanRecommendationIn(RegisteredTableIdentity):
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_bytes: int | None = Field(default=None, ge=0)


class LoadManualPromptIn(LoadPlanRecommendationIn):
    pool_slots: int = Field(default=2, ge=1, le=32)
    max_parallelism_allowed: int = Field(default=32, ge=1, le=32)


class LoadManualValidateIn(LoadPlanRecommendationIn):
    response_text: str = Field(min_length=1, max_length=100000)
    pool_slots: int = Field(default=2, ge=1, le=32)
    max_parallelism_allowed: int = Field(default=32, ge=1, le=32)


class LoadPlanIn(BaseModel):
    system_cd: str = Field(min_length=1, max_length=32)
    instance_name: str = Field(min_length=1, max_length=255)
    postfix: str = Field(default="", max_length=32)
    owner: str = Field(min_length=1, max_length=255)
    table_name: str = Field(min_length=1, max_length=255)
    table_type: str = Field(default="TABLE", max_length=20)
    load_mode: Literal["INIT", "INCREMENTAL"] = "INIT"
    split_strategy: Literal["SINGLE", "SOURCE_PARTITION", "DATE_RANGE", "PK_RANGE", "COMPOSITE"] = "SINGLE"
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_bytes: int | None = Field(default=None, ge=0)
    target_chunk_rows: int = Field(default=1000000, ge=1, le=100000000)
    max_parallelism: int = Field(default=1, ge=1, le=32)
    source_pool: str | None = Field(default=None, max_length=120)
    allowed_window: str | None = Field(default=None, max_length=120)
    source_watermark: str | None = Field(default=None, max_length=255)


class LoadChunkStatusIn(BaseModel):
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"]
    source_rows: int | None = Field(default=None, ge=0)
    staging_rows: int | None = Field(default=None, ge=0)
    error_message: str | None = Field(default=None, max_length=4000)
    validation_status: str | None = Field(default=None, max_length=30)


class PkCandidate(StrictSchema):
    candidate_id: int | None = None
    rank: int = Field(ge=1, le=4)
    columns: list[str] = Field(min_length=1, max_length=6)
    source_type: str
    method: str
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    status: str = "GENERATED"
    validation_status: str = "PENDING"
    model_name: str | None = None
    row_count: int | None = Field(default=None, ge=0)
    null_count: int | None = Field(default=None, ge=0)
    duplicate_group_count: int | None = Field(default=None, ge=0)
    validation_message: str | None = None
    src_snapshot_id: int | None = None


class PkCandidatesGenerateIn(RegisteredTableIdentity):
    pass


class PkCandidatesGenerateResponse(StrictSchema):
    source_pk_applied: bool
    source_pk_columns: list[str] = Field(default_factory=list, max_length=6)
    candidates: list[PkCandidate] = Field(default_factory=list, max_length=4)
    fallback_used: bool = False
    message: str = ""


class PkCandidatesListResponse(StrictSchema):
    current_pk_columns: list[str] = Field(default_factory=list, max_length=6)
    current_pk_source: Literal["SOURCE_PK", "LOGICAL_PK", "NONE"]
    source_pk_columns: list[str] = Field(default_factory=list, max_length=6)
    items: list[PkCandidate] = Field(default_factory=list, max_length=4)
    can_generate: bool = True


class PkCandidateValidateResponse(StrictSchema):
    candidate_id: int
    validation_status: Literal["PENDING", "PASSED", "FAILED", "EMPTY_SOURCE", "UNAVAILABLE", "NOT_REQUIRED"]
    row_count: int | None = Field(default=None, ge=0)
    null_count: int | None = Field(default=None, ge=0)
    duplicate_group_count: int | None = Field(default=None, ge=0)
    message: str = ""


class PkCandidateApplyIn(StrictSchema):
    confirm: bool


class PkCandidateApplyResponse(StrictSchema):
    candidate_id: int
    columns: list[str] = Field(min_length=1, max_length=6)
    status: str


class PkCandidateRejectIn(StrictSchema):
    reason: str = Field(min_length=1, max_length=2000)


class PkCandidateRejectResponse(StrictSchema):
    candidate_id: int
    status: str
    reason: str
