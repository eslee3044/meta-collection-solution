from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)
role_menus = Table(
    "role_menus",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("menu_id", Integer, ForeignKey("menus.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")
    menus: Mapped[list["Menu"]] = relationship(secondary=role_menus, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    roles: Mapped[list[Role]] = relationship(secondary=role_permissions, back_populates="permissions")


class Menu(Base):
    __tablename__ = "menus"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    path: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str] = mapped_column(String(80), default="Circle")
    order: Mapped[int] = mapped_column(default=0)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), nullable=True)
    roles: Mapped[list[Role]] = relationship(secondary=role_menus, back_populates="menus")


class DatalakeTarget(TimestampMixin, Base):
    __tablename__ = "datalake_targets"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    target_type: Mapped[str] = mapped_column(String(40), default="postgresql")
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    credential_version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(30), default="connected")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DatalakeOrchestrationConfig(TimestampMixin, Base):
    __tablename__ = "datalake_orchestration_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(30), default="MANIFEST_ONLY")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Seoul")
    incremental_auto_enable: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DatalakeLoadPlan(TimestampMixin, Base):
    __tablename__ = "datalake_load_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    system_cd: Mapped[str] = mapped_column(String(32), index=True)
    instance_name: Mapped[str] = mapped_column(String(255), index=True)
    postfix: Mapped[str] = mapped_column(String(32), default="")
    owner: Mapped[str] = mapped_column(String(255), index=True)
    table_name: Mapped[str] = mapped_column(String(255), index=True)
    table_type: Mapped[str] = mapped_column(String(20), default="TABLE")
    load_mode: Mapped[str] = mapped_column(String(20), default="INIT")
    split_strategy: Mapped[str] = mapped_column(String(30), default="SINGLE")
    estimated_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_chunk_rows: Mapped[int] = mapped_column(BigInteger, default=1000000)
    max_parallelism: Mapped[int] = mapped_column(Integer, default=1)
    source_pool: Mapped[str | None] = mapped_column(String(120), nullable=True)
    allowed_window: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_watermark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    initial_status: Mapped[str] = mapped_column(String(30), default="NOT_READY")
    incremental_status: Mapped[str] = mapped_column(String(30), default="LOCKED")
    dag_manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DatalakeLoadChunk(TimestampMixin, Base):
    __tablename__ = "datalake_load_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("datalake_load_plans.id", ondelete="CASCADE"), index=True)
    chunk_no: Mapped[int] = mapped_column(Integer)
    range_start: Mapped[str | None] = mapped_column(String(255), nullable=True)
    range_end: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    staging_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatalakeLoadDag(TimestampMixin, Base):
    __tablename__ = "datalake_load_dags"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("datalake_load_plans.id", ondelete="CASCADE"), index=True)
    dag_type: Mapped[str] = mapped_column(String(20))
    dag_id: Mapped[str] = mapped_column(String(180), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manifest_json: Mapped[str] = mapped_column(Text)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    db_type: Mapped[str] = mapped_column(String(40), index=True)
    host: Mapped[str] = mapped_column(String(255), default="localhost")
    port: Mapped[int | None] = mapped_column(nullable=True)
    database: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str] = mapped_column(String(255), default="")
    secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ssh_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_port: Mapped[int] = mapped_column(default=22)
    ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_auth_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ssh_secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="unchecked")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs: Mapped[list["CollectionJob"]] = relationship(back_populates="data_source", cascade="all, delete-orphan")


class CollectionJob(TimestampMixin, Base):
    __tablename__ = "collection_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    schedule_type: Mapped[str] = mapped_column(String(20), default="cron")
    cron: Mapped[str] = mapped_column(String(100), default="0 2 * * *")
    interval_minutes: Mapped[int | None] = mapped_column(nullable=True)
    schemas: Mapped[list[str]] = mapped_column(JSON, default=list)
    collection_items: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["INDEX", "TABLE", "VIEW", "PROCEDURE", "SELECT PRIVILEGE"])
    collect_storage: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_source: Mapped[DataSource] = relationship(back_populates="jobs")
    runs: Mapped[list["CollectionRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    current_step: Mapped[str] = mapped_column(String(80), default="queued")
    current_schema: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    object_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job: Mapped[CollectionJob] = relationship(back_populates="runs")
    logs: Mapped[list["RunLog"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="RunLog.sequence")


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(default=0, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    step: Mapped[str] = mapped_column(String(80), default="unknown")
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped[CollectionRun] = relationship(back_populates="logs")


class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)


class MetaTableExt(Base):
    __tablename__ = "TB_META_TABLES_EXT"
    __table_args__ = {"schema": "EAPET", "quote": True}

    system_cd: Mapped[str] = mapped_column(String(32), primary_key=True)
    instance_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    postfix: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    etl_conn_div_cd: Mapped[str | None] = mapped_column(String(32), nullable=True)
    etl_conn_nm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tgt_ds_cd: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tgt_table_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tgt_database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instance_div_cd: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdon: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdby: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lastupdated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updatedby: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sess_name_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    mapp_name_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    tgt_name_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    partition_col_modifiable_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    table_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    src_data_source_id: Mapped[int | None] = mapped_column("SRC_DATA_SOURCE_ID", Integer, nullable=True)
    src_snapshot_id: Mapped[int | None] = mapped_column("SRC_SNAPSHOT_ID", Integer, nullable=True)
    src_schema_fingerprint: Mapped[str | None] = mapped_column("SRC_SCHEMA_FINGERPRINT", String(64), nullable=True)
    src_prev_schema_fingerprint: Mapped[str | None] = mapped_column("SRC_PREV_SCHEMA_FINGERPRINT", String(64), nullable=True)
    layout_status: Mapped[str] = mapped_column("LAYOUT_STATUS", String(30), default="UNCHANGED")
    layout_change_yn: Mapped[str] = mapped_column("LAYOUT_CHANGE_YN", String(1), default="N")
    layout_change_count: Mapped[int] = mapped_column("LAYOUT_CHANGE_COUNT", Integer, default=0)
    last_layout_snapshot_id: Mapped[int | None] = mapped_column("LAST_LAYOUT_SNAPSHOT_ID", Integer, nullable=True)
    last_layout_changed_at: Mapped[datetime | None] = mapped_column("LAST_LAYOUT_CHANGED_AT", DateTime(timezone=True), nullable=True)
    metadata_sync_status: Mapped[str] = mapped_column("METADATA_SYNC_STATUS", String(30), default="APPLIED")
    metadata_sync_message: Mapped[str | None] = mapped_column("METADATA_SYNC_MESSAGE", Text, nullable=True)
    is_active: Mapped[str] = mapped_column("IS_ACTIVE", String(1), default="Y")
    sql_insp_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    sql_src_count: Mapped[str | None] = mapped_column("sql_src_tcount", String(4000), nullable=True)
    sql_tgt_count: Mapped[str | None] = mapped_column("sql_tgt_tcount", String(4000), nullable=True)
    sql_tgt_pk_dup: Mapped[int | None] = mapped_column("sql_tgt_pk_dup", Integer, nullable=True)

class MetaColumnExt(Base):
    __tablename__ = "TB_META_COLUMNS_EXT"
    __table_args__ = {"schema": "EAPET", "quote": True}

    system_cd: Mapped[str] = mapped_column(String(32), primary_key=True)
    instance_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    postfix: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    column_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    src_column_name: Mapped[str | None] = mapped_column("SRC_COLUMN_NAME", String(255), nullable=True)
    tgt_column_name: Mapped[str | None] = mapped_column("TGT_COLUMN_NAME", String(255), nullable=True)
    src_snapshot_id: Mapped[int | None] = mapped_column("SRC_SNAPSHOT_ID", Integer, nullable=True)
    src_column_fingerprint: Mapped[str | None] = mapped_column("SRC_COLUMN_FINGERPRINT", String(64), nullable=True)
    column_status: Mapped[str] = mapped_column("COLUMN_STATUS", String(30), default="ACTIVE")
    column_change_yn: Mapped[str] = mapped_column("COLUMN_CHANGE_YN", String(1), default="N")
    column_change_type: Mapped[str | None] = mapped_column("COLUMN_CHANGE_TYPE", String(40), nullable=True)
    last_layout_snapshot_id: Mapped[int | None] = mapped_column("LAST_LAYOUT_SNAPSHOT_ID", Integer, nullable=True)
    last_layout_changed_at: Mapped[datetime | None] = mapped_column("LAST_LAYOUT_CHANGED_AT", DateTime(timezone=True), nullable=True)
    metadata_sync_status: Mapped[str] = mapped_column("METADATA_SYNC_STATUS", String(30), default="APPLIED")
    metadata_sync_message: Mapped[str | None] = mapped_column("METADATA_SYNC_MESSAGE", Text, nullable=True)
    is_active: Mapped[str] = mapped_column("IS_ACTIVE", String(1), default="Y")
    column_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_precision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    null_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    pk_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    partition_key_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    cluster_key_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    update_base_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    to_single_byte_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    substr_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdon: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdby: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lastupdated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updatedby: Mapped[str | None] = mapped_column(String(255), nullable=True)


class MetaPkCandidate(Base):
    __tablename__ = "TB_META_PK_CANDIDATES_EXT"
    __table_args__ = (
        Index("TB_META_PK_CANDIDATES_EXT_LOOKUP_IDX", "SYSTEM_CD", "INSTANCE_NAME", "POSTFIX", "OWNER", "TABLE_NAME", "STATUS"),
        Index("TB_META_PK_CANDIDATES_EXT_SNAPSHOT_IDX", "SRC_SNAPSHOT_ID"),
        {"schema": "EAPET", "quote": True},
    )

    candidate_id: Mapped[int] = mapped_column("CANDIDATE_ID", primary_key=True)
    system_cd: Mapped[str] = mapped_column("SYSTEM_CD", String(32), nullable=False)
    instance_name: Mapped[str] = mapped_column("INSTANCE_NAME", String(255), nullable=False)
    postfix: Mapped[str] = mapped_column("POSTFIX", String(32), nullable=False)
    owner: Mapped[str] = mapped_column("OWNER", String(255), nullable=False)
    table_name: Mapped[str] = mapped_column("TABLE_NAME", String(255), nullable=False)
    object_type: Mapped[str] = mapped_column("OBJECT_TYPE", String(20), nullable=False)
    src_data_source_id: Mapped[int | None] = mapped_column("SRC_DATA_SOURCE_ID", Integer, nullable=True)
    src_snapshot_id: Mapped[int | None] = mapped_column("SRC_SNAPSHOT_ID", Integer, nullable=True)
    candidate_rank: Mapped[int] = mapped_column("CANDIDATE_RANK", Integer, nullable=False)
    candidate_columns_json: Mapped[str] = mapped_column("CANDIDATE_COLUMNS_JSON", Text, nullable=False)
    candidate_fingerprint: Mapped[str] = mapped_column("CANDIDATE_FINGERPRINT", String(64), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column("SOURCE_TYPE", String(40), nullable=False)
    method: Mapped[str] = mapped_column("METHOD", String(40), nullable=False)
    model_name: Mapped[str | None] = mapped_column("MODEL_NAME", String(120), nullable=True)
    confidence: Mapped[float] = mapped_column("CONFIDENCE", Numeric(5, 4), nullable=False)
    reason: Mapped[str | None] = mapped_column("REASON", Text, nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(30), nullable=False)
    validation_status: Mapped[str] = mapped_column("VALIDATION_STATUS", String(30), nullable=False)
    row_count: Mapped[int | None] = mapped_column("ROW_COUNT", BigInteger, nullable=True)
    null_count: Mapped[int | None] = mapped_column("NULL_COUNT", BigInteger, nullable=True)
    duplicate_group_count: Mapped[int | None] = mapped_column("DUPLICATE_GROUP_COUNT", BigInteger, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column("VALIDATED_AT", DateTime(timezone=True), nullable=True)
    validation_message: Mapped[str | None] = mapped_column("VALIDATION_MESSAGE", Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column("CREATED_BY", String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column("CREATED_AT", DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column("REVIEWED_BY", String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column("REVIEWED_AT", DateTime(timezone=True), nullable=True)
    applied_by: Mapped[str | None] = mapped_column("APPLIED_BY", String(255), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column("APPLIED_AT", DateTime(timezone=True), nullable=True)


class MetaLayoutChange(Base):
    __tablename__ = "TB_META_LAYOUT_CHANGES_EXT"
    __table_args__ = {"schema": "EAPET", "quote": True}

    id: Mapped[int] = mapped_column("CHANGE_ID", primary_key=True)
    system_cd: Mapped[str | None] = mapped_column("SYSTEM_CD", String(32), nullable=True, index=True)
    instance_name: Mapped[str | None] = mapped_column("INSTANCE_NAME", String(255), nullable=True, index=True)
    postfix: Mapped[str | None] = mapped_column("POSTFIX", String(32), nullable=True)
    owner: Mapped[str | None] = mapped_column("OWNER", String(255), nullable=True)
    table_name: Mapped[str | None] = mapped_column("TABLE_NAME", String(255), nullable=True, index=True)
    object_type: Mapped[str] = mapped_column("OBJECT_TYPE", String(20), default="TABLE")
    column_name: Mapped[str | None] = mapped_column("COLUMN_NAME", String(255), nullable=True)
    change_type: Mapped[str] = mapped_column("CHANGE_TYPE", String(60))
    risk_level: Mapped[str] = mapped_column("RISK_LEVEL", String(20), default="REVIEW")
    change_path: Mapped[str | None] = mapped_column("CHANGE_PATH", String(255), nullable=True)
    before_value: Mapped[str | None] = mapped_column("BEFORE_VALUE", Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column("AFTER_VALUE", Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column("CHANGE_DETAIL_JSON", Text, nullable=True)
    before_snapshot_id: Mapped[int | None] = mapped_column("BEFORE_SNAPSHOT_ID", Integer, nullable=True, index=True)
    after_snapshot_id: Mapped[int | None] = mapped_column("AFTER_SNAPSHOT_ID", Integer, nullable=True, index=True)
    change_fingerprint: Mapped[str] = mapped_column("CHANGE_FINGERPRINT", String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column("CHANGE_STATUS", String(30), default="REVIEW_REQUIRED", index=True)
    detected_at: Mapped[datetime] = mapped_column("DETECTED_AT", DateTime(timezone=True), default=utcnow)
    reviewed_by: Mapped[str | None] = mapped_column("REVIEWED_BY", String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column("REVIEWED_AT", DateTime(timezone=True), nullable=True)
    applied_by: Mapped[str | None] = mapped_column("APPLIED_BY", String(255), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column("APPLIED_AT", DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column("REJECT_REASON", Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column("ERROR_MESSAGE", Text, nullable=True)


class MetaLayoutChangeAction(Base):
    __tablename__ = "TB_META_LAYOUT_CHANGE_ACTIONS_EXT"
    __table_args__ = {"schema": "EAPET", "quote": True}

    id: Mapped[int] = mapped_column("ACTION_ID", primary_key=True)
    change_id: Mapped[int] = mapped_column("CHANGE_ID", Integer, index=True)
    action_type: Mapped[str] = mapped_column("ACTION_TYPE", String(30))
    action_comment: Mapped[str | None] = mapped_column("ACTION_COMMENT", Text, nullable=True)
    actor: Mapped[str] = mapped_column("ACTOR", String(255))
    acted_at: Mapped[datetime] = mapped_column("ACTED_AT", DateTime(timezone=True), default=utcnow)


class MetaTableConfig(TimestampMixin, Base):
    __tablename__ = "meta_table_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    source_type: Mapped[str] = mapped_column(String(20), default="internal")
    external_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True)
    schema_name: Mapped[str] = mapped_column(String(255), default="EAPET")
    tables_table_name: Mapped[str] = mapped_column(String(255), default="TB_META_TABLES_EXT")
    columns_table_name: Mapped[str] = mapped_column(String(255), default="TB_META_COLUMNS_EXT")
    target_database_name: Mapped[str] = mapped_column(String(255), default="PostgreSQL")
    description_ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description_ai_provider: Mapped[str] = mapped_column(String(30), default="rules", nullable=False)
    description_ai_model: Mapped[str] = mapped_column(String(120), default="qwen3:latest", nullable=False)
