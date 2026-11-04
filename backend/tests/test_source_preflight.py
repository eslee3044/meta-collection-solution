from app import main
from app.models import DataSource
from app.schemas import DataSourceIn


def test_unsaved_source_preflight_tests_without_persisting(monkeypatch):
    calls = {}

    def fake_apply(item: DataSource, payload: DataSourceIn):
        calls["item"] = item
        calls["payload"] = payload

    def fake_test(item: DataSource):
        calls["tested"] = item

    monkeypatch.setattr(main, "apply_source", fake_apply)
    monkeypatch.setattr(main, "test_source", fake_test)

    payload = DataSourceIn(name="temporary", db_type="sqlite", database=":memory:")
    result = main._test_source_payload(payload)

    assert result == {"status": "connected"}
    assert calls["payload"] is payload
    assert calls["tested"] is calls["item"]
    assert calls["item"].id is None


def test_unsaved_source_permission_preview_does_not_persist(monkeypatch):
    calls = {}

    def fake_apply(item: DataSource, payload: DataSourceIn):
        calls["item"] = item

    def fake_preview(item: DataSource):
        calls["previewed"] = item
        return {"status": "complete", "schemas": []}

    monkeypatch.setattr(main, "apply_source", fake_apply)
    monkeypatch.setattr(main, "preview_source_permissions", fake_preview)

    payload = DataSourceIn(name="temporary", db_type="sqlite", database=":memory:")
    result = main._preview_source_payload(payload)

    assert result["status"] == "complete"
    assert calls["previewed"] is calls["item"]
    assert calls["previewed"].id is None
