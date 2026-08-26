from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Table, Text
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
    __table_args__ = {"quote": True}

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
    sql_insp_yn: Mapped[str | None] = mapped_column(String(1), nullable=True)
    sql_src_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sql_tgt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sql_tgt_pk_dup: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MetaColumnExt(Base):
    __tablename__ = "TB_META_COLUMNS_EXT"
    __table_args__ = {"quote": True}

    system_cd: Mapped[str] = mapped_column(String(32), primary_key=True)
    instance_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    postfix: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    column_name: Mapped[str] = mapped_column(String(255), primary_key=True)
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
