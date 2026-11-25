"""Disposable-PostgreSQL integration tests; never point at an operational target."""
import hashlib
import json
import os
import uuid

import psycopg
import pytest

from app import datalake_postgres as adapter

DSN = os.getenv("METAVAULT_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="requires explicit disposable PostgreSQL URL")


def _dsn() -> str:
    assert DSN
    return DSN


def _bootstrap(st_schema: str, l0_schema: str, *, value_column: bool = False):
    conn = psycopg.connect(_dsn())
    with conn.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA "{st_schema}"')
        cursor.execute(f'CREATE SCHEMA "{l0_schema}"')
        suffix = ', "VALUE" TEXT' if value_column else ''
        cursor.execute(f'CREATE TABLE "{st_schema}".orders ("ID" INTEGER NOT NULL{suffix})')
        cursor.execute(f'CREATE TABLE "{l0_schema}".orders ("ID" INTEGER NOT NULL{suffix}, CONSTRAINT pk_orders PRIMARY KEY ("ID"))')
    conn.commit()
    return conn


def _fingerprint(conn, st_schema: str, l0_schema: str):
    with conn.cursor() as cursor:
        inspected = adapter._inspect_migration_with_cursor(cursor, [(st_schema, "orders"), (l0_schema, "orders")])
    conn.commit()  # release ACCESS SHARE locks before apply takes ACCESS EXCLUSIVE
    return hashlib.sha256(json.dumps(inspected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _ddl(st_schema: str, l0_schema: str, columns: str):
    return (f'CREATE SCHEMA IF NOT EXISTS "{st_schema}"; CREATE SCHEMA IF NOT EXISTS "{l0_schema}"; '
            f'CREATE TABLE IF NOT EXISTS "{st_schema}".orders ({columns}); '
            f'CREATE TABLE IF NOT EXISTS "{l0_schema}".orders ({columns}, CONSTRAINT pk_orders PRIMARY KEY ("ID"));')


def _run(st_schema, l0_schema, expected, desired, ddl, plan_key=None):
    original = adapter._connect_postgres
    adapter._connect_postgres = lambda: psycopg.connect(_dsn())
    try:
        return adapter.apply_empty_postgresql_migration(
            st_schema=st_schema, st_table="orders", l0_schema=l0_schema, l0_table="orders",
            desired_columns=desired, desired_pk_columns=["ID"], ddl=ddl,
            plan_key=plan_key or uuid.uuid4().hex, expected_physical_fingerprint=expected,
            expected_spec_fingerprint="a" * 64,
        )
    finally:
        adapter._connect_postgres = original


def _cleanup(conn, st_schema, l0_schema):
    with conn.cursor() as cursor:
        cursor.execute(f'DROP SCHEMA IF EXISTS "{st_schema}" CASCADE')
        cursor.execute(f'DROP SCHEMA IF EXISTS "{l0_schema}" CASCADE')
    conn.commit()
    conn.close()


def test_empty_pair_nullable_tail_add_is_atomic_and_idempotent():
    st_schema, l0_schema = f"mvst_{uuid.uuid4().hex[:10]}", f"mvl0_{uuid.uuid4().hex[:10]}"
    conn = _bootstrap(st_schema, l0_schema)
    try:
        before = _fingerprint(conn, st_schema, l0_schema)
        desired = [{"name": "ID", "type": "INTEGER", "nullable": False}, {"name": "NOTE", "type": "TEXT", "nullable": True}]
        ddl = _ddl(st_schema, l0_schema, '"ID" INTEGER NOT NULL, "NOTE" TEXT')
        key = "0" + "a" * 31  # valid fixed-format key beginning with a digit
        result = _run(st_schema, l0_schema, before, desired, ddl, key)
        assert result["status"] == "applied"
        with conn.cursor() as cursor:
            columns = cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='orders' ORDER BY ordinal_position", (st_schema,)).fetchall()
        assert [row[0] for row in columns] == ["ID", "NOTE"]
        repeated = _run(st_schema, l0_schema, before, desired, ddl, key)
        assert repeated["idempotent"] is True
    finally:
        _cleanup(conn, st_schema, l0_schema)


def test_middle_column_addition_rebuild_preserves_desired_order():
    st_schema, l0_schema = f"mvst_{uuid.uuid4().hex[:10]}", f"mvl0_{uuid.uuid4().hex[:10]}"
    conn = _bootstrap(st_schema, l0_schema, value_column=True)
    try:
        before = _fingerprint(conn, st_schema, l0_schema)
        desired = [
            {"name": "ID", "type": "INTEGER", "nullable": False},
            {"name": "NOTE", "type": "TEXT", "nullable": True},
            {"name": "VALUE", "type": "TEXT", "nullable": True},
        ]
        ddl = _ddl(st_schema, l0_schema, '"ID" INTEGER NOT NULL, "NOTE" TEXT, "VALUE" TEXT')
        result = _run(st_schema, l0_schema, before, desired, ddl)
        assert result["status"] == "applied"
        with conn.cursor() as cursor:
            columns = cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='orders' ORDER BY ordinal_position", (st_schema,)).fetchall()
        assert [row[0] for row in columns] == ["ID", "NOTE", "VALUE"]
    finally:
        _cleanup(conn, st_schema, l0_schema)


def test_stale_nonempty_target_is_rejected_without_ddl():
    st_schema, l0_schema = f"mvst_{uuid.uuid4().hex[:10]}", f"mvl0_{uuid.uuid4().hex[:10]}"
    conn = _bootstrap(st_schema, l0_schema)
    try:
        before = _fingerprint(conn, st_schema, l0_schema)
        with conn.cursor() as cursor:
            cursor.execute(f'INSERT INTO "{l0_schema}".orders ("ID") VALUES (7)')
        conn.commit()
        desired = [{"name": "ID", "type": "INTEGER", "nullable": False}, {"name": "NOTE", "type": "TEXT", "nullable": True}]
        ddl = _ddl(st_schema, l0_schema, '"ID" INTEGER NOT NULL, "NOTE" TEXT')
        with pytest.raises(ValueError, match="PLAN_STALE|BLOCKED"):
            _run(st_schema, l0_schema, before, desired, ddl)
        with conn.cursor() as cursor:
            names = cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='orders' ORDER BY ordinal_position", (st_schema,)).fetchall()
            rows = cursor.execute(f'SELECT "ID" FROM "{l0_schema}".orders').fetchall()
        assert [row[0] for row in names] == ["ID"]
        assert rows == [(7,)]
    finally:
        _cleanup(conn, st_schema, l0_schema)
