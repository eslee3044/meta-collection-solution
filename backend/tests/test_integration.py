from datetime import datetime, timezone
from types import SimpleNamespace

from app.integration import snapshot_diff, snapshot_summary


def snap(snapshot_id, payload):
    return SimpleNamespace(
        id=snapshot_id,
        data_source_id=7,
        run_id=snapshot_id + 10,
        captured_at=datetime(2026, 1, snapshot_id, tzinfo=timezone.utc),
        fingerprint=f"fp-{snapshot_id}",
        payload=payload,
    )


def test_snapshot_summary_counts_objects():
    item = snap(1, {"source": "demo", "schemas": [{"name": "public", "tables": [{"name": "users", "columns": [{"name": "id"}]}], "views": [], "procedures": []}]})
    result = snapshot_summary(item)
    assert result["schema_count"] == 1
    assert result["table_count"] == 1
    assert result["source"] == "demo"


def test_snapshot_diff_reports_added_removed_and_changed_objects():
    before = snap(1, {"schemas": [{"name": "public", "tables": [{"name": "users", "columns": [{"name": "id", "type": "integer"}]}]}]})
    after = snap(2, {"schemas": [{"name": "public", "tables": [{"name": "users", "columns": [{"name": "id", "type": "bigint"}, {"name": "email", "type": "text"}]}, {"name": "orders", "columns": []}]}]})
    result = snapshot_diff(before, after)
    assert any(item["key"] == "table:public.orders" for item in result["added"])
    assert any(item["key"] == "column:public.users.email" for item in result["added"])
    assert any(item["key"] == "column:public.users.id" for item in result["changed"])
    assert result["counts"]["removed"] == 0
