from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app import pk_validation
from app.models import DataSource


def source_snapshot(*, columns=None, object_name="orders", object_type="TABLE"):
    columns = columns or ["order_id", "line_no"]
    obj = {
        "name": object_name,
        "columns": [{"name": name} for name in columns],
    }
    key = "views" if object_type == "VIEW" else "tables"
    return {"schemas": [{"name": "main", key: [obj]}]}


def make_source():
    return DataSource(name="source", db_type="sqlite", database=":memory:", host="", username="")


def test_validation_passes_for_table_and_returns_counts_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "orders" ("order_id" INTEGER, "line_no" INTEGER)'))
        conn.execute(text('INSERT INTO "orders" VALUES (1, 1), (2, 1)'))
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(), "orders", ["order_id", "line_no"]
    )

    assert result.status == "PASSED"
    assert result.row_count == 2
    assert result.null_count == 0
    assert result.duplicate_group_count == 0
    assert not any(value in result.__dict__ for value in ((1,), (2,)))


def test_validation_supports_views_and_fails_on_nulls(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "raw_orders" ("order_id" INTEGER, "line_no" INTEGER)'))
        conn.execute(text('INSERT INTO "raw_orders" VALUES (1, NULL), (2, 1)'))
        conn.execute(text('CREATE VIEW "orders_view" AS SELECT order_id, line_no FROM raw_orders'))
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(object_name="orders_view", object_type="VIEW"),
        "orders_view", ["order_id", "line_no"]
    )

    assert result.status == "FAILED"
    assert result.row_count == 2
    assert result.null_count == 1
    assert "NULL" in result.message


def test_validation_fails_on_duplicate_groups_without_returning_duplicate_values(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "orders" ("order_id" INTEGER, "line_no" INTEGER)'))
        conn.execute(text('INSERT INTO "orders" VALUES (1, 1), (1, 1), (2, 1)'))
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(), "orders", ["order_id", "line_no"]
    )

    assert result.status == "FAILED"
    assert result.duplicate_group_count == 1
    assert "1" not in result.message


def test_empty_source_is_not_passed(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "orders" ("order_id" INTEGER, "line_no" INTEGER)'))
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(), "orders", ["order_id", "line_no"]
    )

    assert result.status == "EMPTY_SOURCE"
    assert result.row_count == 0


@pytest.mark.parametrize("columns", [["missing"], ["order_id", "missing"]])
def test_stale_or_missing_snapshot_columns_fail_closed(monkeypatch, columns):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(columns=["order_id", "line_no"]), "orders", columns
    )

    assert result.status == "FAILED"
    assert result.row_count is None
    assert "컬럼" in result.message


def test_identifiers_are_allowlisted_and_dialect_quoted(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "order data" ("select" INTEGER)'))
        conn.execute(text('INSERT INTO "order data" VALUES (1)'))
    monkeypatch.setattr(pk_validation, "source_engine", lambda source: engine)

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(columns=["select"], object_name="order data"),
        "order data", ["select"]
    )

    assert result.status == "PASSED"


def test_permission_or_timeout_is_unavailable_and_redacted(monkeypatch):
    class BrokenConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("permission denied for user=secret password=hunter2 postgresql://secret")

    class BrokenEngine:
        dialect = create_engine("sqlite://").dialect

        def connect(self):
            return BrokenConnection()

    monkeypatch.setattr(pk_validation, "source_engine", lambda source: BrokenEngine())

    result = pk_validation.validate_source_data(
        make_source(), source_snapshot(), "orders", ["order_id", "line_no"]
    )

    assert result.status == "UNAVAILABLE"
    assert result.row_count is None
    assert "hunter2" not in result.message
    assert "postgresql" not in result.message
    assert "권한" in result.message or "접근" in result.message
