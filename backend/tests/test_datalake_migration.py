from types import SimpleNamespace

import pytest

from app.datalake_ddl import build_table_spec
from app.datalake_migration import (
    apply_column_metadata_change,
    classify_target_state,
    compare_table_layouts,
)


def _spec(columns=None):
    return build_table_spec({
        "system_cd": "CRM",
        "owner": "PUBLIC",
        "table_name": "CUSTOMERS",
        "tgt_ds_cd": "ST_CRM",
        "tgt_table_name": "CUSTOMERS",
        "columns": columns or [{"column_name": "ID", "data_type": "INTEGER", "pk_yn": "Y", "null_yn": "N"}],
    })


def _column(**updates):
    fields = dict(column_id=8, column_status="ACTIVE", is_active="Y", data_type="TEXT", data_length=10,
                  data_precision=None, data_scale=None, null_yn="Y", comments=None,
                  metadata_sync_status="APPLIED", metadata_sync_message=None,
                  column_change_yn="Y", column_change_type=None, last_layout_snapshot_id=None)
    fields.update(updates)
    return SimpleNamespace(**fields)


def test_classify_missing_pair_as_create_new():
    result = classify_target_state(st_exists=False, l0_exists=False, st_rows=None, l0_rows=None)
    assert result["route"] == "CREATE_NEW"
    assert result["initial_load_required"] is True


@pytest.mark.parametrize("st,l0", [(None, 0), (0, None), (-1, 0), (True, 0)])
def test_unknown_or_invalid_count_is_blocked(st, l0):
    assert classify_target_state(st_exists=True, l0_exists=True, st_rows=st, l0_rows=l0)["status"] == "BLOCKED"


def test_one_sided_pair_is_blocked():
    assert classify_target_state(st_exists=True, l0_exists=False, st_rows=0, l0_rows=None)["status"] == "BLOCKED"


def test_empty_pair_skips_initial_load():
    result = classify_target_state(st_exists=True, l0_exists=True, st_rows=0, l0_rows=0)
    assert result["route"] == "APPLY_EMPTY"
    assert result["initial_load_required"] is False


def test_populated_pair_requires_tobe():
    result = classify_target_state(st_exists=True, l0_exists=True, st_rows=0, l0_rows=1)
    assert result["route"] == "TOBE_REQUIRED"


def test_layout_comparison_allows_nullable_addition_only():
    result = compare_table_layouts([{"name": "ID", "type": "INTEGER", "nullable": False}], [
        {"name": "ID", "type": "INTEGER", "nullable": False},
        {"name": "NOTE", "type": "TEXT", "nullable": True},
    ])
    assert result["alter_compatible"] is True
    assert result["requires_rebuild"] is False


def test_middle_column_addition_requires_rebuild_to_preserve_ordinal():
    result = compare_table_layouts(
        [{"name": "ID", "type": "INTEGER"}, {"name": "NOTE", "type": "TEXT"}],
        [{"name": "ID", "type": "INTEGER"}, {"name": "CREATED_AT", "type": "DATE"}, {"name": "NOTE", "type": "TEXT"}],
    )
    assert result["added_in_middle"] is True
    assert result["alter_compatible"] is False
    assert result["requires_rebuild"] is True


def test_layout_comparison_requires_rebuild_for_order_and_type_change():
    result = compare_table_layouts(
        [{"name": "ID", "type": "INTEGER"}, {"name": "NOTE", "type": "TEXT"}],
        [{"name": "NOTE", "type": "TEXT"}, {"name": "ID", "type": "BIGINT"}],
    )
    assert result["order_changed"] is True
    assert result["requires_rebuild"] is True


def test_layout_comparison_rejects_duplicate_names():
    with pytest.raises(ValueError):
        compare_table_layouts([{"name": "ID"}, {"name": "id"}], [])


def test_apply_column_metadata_change_preserves_approved_ordinal():
    column = _column()
    apply_column_metadata_change(column, {"ordinal_position": 2, "type": "VARCHAR", "length": 40, "nullable": False}, "COLUMN_CHANGED", 99)
    assert column.column_id == 2
    assert column.data_type == "VARCHAR"
    assert column.data_length == 40
    assert column.null_yn == "N"
    assert column.metadata_sync_status == "DATALAKE_PENDING"


def test_removed_column_is_not_reactivated_even_with_after_payload():
    column = _column()
    apply_column_metadata_change(column, {"ordinal_position": 1, "type": "INTEGER"}, "COLUMN_REMOVED", 100)
    assert column.column_status == "INACTIVE"
    assert column.is_active == "N"


def test_migration_status_is_false_when_layout_matches():
    from app.datalake_migration import build_migration_status

    physical = {"objects": [
        {"schema": "st", "table": "orders", "exists": True, "has_rows": False, "columns": [{"name": "ID", "type": "INTEGER", "nullable": False}], "primary_key": [], "safe_to_rebuild": True, "dependencies": []},
        {"schema": "l0", "table": "orders", "exists": True, "has_rows": False, "columns": [{"name": "ID", "type": "INTEGER", "nullable": False}], "primary_key": ["ID"], "safe_to_rebuild": True, "dependencies": []},
    ], "blocking_reasons": []}
    result = build_migration_status(identity={"table_name": "orders"}, strategy="MERGE", desired_pk_columns=["ID"], st={"schema": "st", "table": "orders"}, l0={"schema": "l0", "table": "orders"}, desired=[{"name": "ID", "type": "INTEGER", "nullable": False}], physical=physical)

    assert result["needs_migration"] is False
    assert result["route"] == "NO_CHANGE"


def test_migration_status_is_true_when_layout_differs():
    from app.datalake_migration import build_migration_status

    physical = {"objects": [
        {"schema": "st", "table": "orders", "exists": True, "has_rows": False, "columns": [{"name": "ID", "type": "INTEGER", "nullable": False}], "primary_key": [], "safe_to_rebuild": True, "dependencies": []},
        {"schema": "l0", "table": "orders", "exists": True, "has_rows": False, "columns": [{"name": "ID", "type": "INTEGER", "nullable": False}], "primary_key": ["ID"], "safe_to_rebuild": True, "dependencies": []},
    ], "blocking_reasons": []}
    result = build_migration_status(identity={"table_name": "orders"}, strategy="MERGE", desired_pk_columns=["ID"], st={"schema": "st", "table": "orders"}, l0={"schema": "l0", "table": "orders"}, desired=[{"name": "ID", "type": "INTEGER", "nullable": False}, {"name": "NOTE", "type": "TEXT", "nullable": True}], physical=physical)

    assert result["needs_migration"] is True
    assert result["changed"] is True
    assert result["route"] == "APPLY_EMPTY"


def test_migration_status_api_is_read_only(monkeypatch):
    import app.main as main
    from app.schemas import RegisteredTableIdentity
    from app.datalake_ddl import table_layout_columns

    spec = _spec()
    desired = table_layout_columns(spec)
    physical = {"objects": [
        {"schema": spec.st_schema, "table": spec.st_table, "exists": True, "has_rows": False, "columns": desired, "primary_key": [], "safe_to_rebuild": True, "dependencies": []},
        {"schema": spec.l0_schema, "table": spec.l0_table, "exists": True, "has_rows": False, "columns": desired, "primary_key": list(spec.pk_columns), "safe_to_rebuild": True, "dependencies": []},
    ], "blocking_reasons": []}
    class Session:
        def add(self, *_args, **_kwargs):
            pytest.fail("status check must not persist a migration plan")
        def commit(self):
            pytest.fail("status check must not commit a migration plan")
    monkeypatch.setattr(main, "target_status", lambda _session: {"configured": True, "target_type": "postgresql"})
    monkeypatch.setattr(main, "_registered_table_spec", lambda _session, _identity: spec)
    monkeypatch.setattr(main, "inspect_postgresql_migration_pair", lambda *_args: physical)
    identity = RegisteredTableIdentity(system_cd="CRM", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS")

    result = main.datalake_schema_migration_status(identity, Session(), None)

    assert result["needs_migration"] is False
    assert result["route"] == "NO_CHANGE"


def test_registered_table_spec_excludes_inactive_columns_and_uses_column_order():
    import app.main as main
    from app.models import MetaColumnExt, MetaTableExt
    from app.schemas import RegisteredTableIdentity

    table = MetaTableExt(system_cd="TEST", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS", tgt_ds_cd="ST_TEST", tgt_table_name="CUSTOMERS")
    columns = [
        MetaColumnExt(system_cd="TEST", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS", column_name="REMOVED", column_id=1, data_type="TEXT", is_active="N", column_status="INACTIVE"),
        MetaColumnExt(system_cd="TEST", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS", column_name="SECOND", column_id=3, data_type="TEXT", is_active="Y", column_status="ACTIVE"),
        MetaColumnExt(system_cd="TEST", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS", column_name="FIRST", column_id=2, data_type="INTEGER", is_active="Y", column_status="ACTIVE"),
    ]
    class Rows:
        def all(self):
            return columns
    class Session:
        def scalar(self, *_args, **_kwargs):
            return table
        def scalars(self, *_args, **_kwargs):
            return Rows()
    identity = RegisteredTableIdentity(system_cd="TEST", instance_name="INSTANCE", postfix="", owner="PUBLIC", table_name="CUSTOMERS")
    spec = main._registered_table_spec(Session(), identity)
    assert [column.name for column in spec.columns] == ["FIRST", "SECOND"]
