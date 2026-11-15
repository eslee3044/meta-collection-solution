from app.ai_description import suggest_descriptions


def test_rules_only_generates_missing_descriptions_without_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("rules provider must not call a network")

    monkeypatch.setattr("app.ai_description.urlopen", fail)
    result = suggest_descriptions([
        {"column_name": "CUSTOMER_ID", "data_type": "INTEGER", "comments": ""},
        {"column_name": "USE_YN", "data_type": "CHAR", "comments": "기존 설명"},
    ], provider="rules")

    assert [item["column_name"] for item in result] == ["CUSTOMER_ID"]
    assert result[0]["method"] == "offline-rules"
    assert result[0]["description"]


def test_ollama_failure_falls_back_to_offline_rules(monkeypatch):
    monkeypatch.setattr("app.ai_description.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    result = suggest_descriptions([{"column_name": "CREATED_AT", "data_type": "TIMESTAMP"}], provider="ollama")

    assert result[0]["method"] == "offline-rules"
    assert result[0]["description"] == "생성 일시"


def test_ollama_rejects_non_local_url(monkeypatch):
    monkeypatch.setenv("METAVAULT_LOCAL_AI_URL", "https://example.com")
    result = suggest_descriptions([{"column_name": "USER_ID", "data_type": "INTEGER"}], provider="ollama")

    assert result[0]["method"] == "offline-rules"


def test_rules_generate_table_description():
    from app.ai_description import suggest_table_description

    result = suggest_table_description("orders", [{"column_name": "order_id", "data_type": "INTEGER"}], "rules")

    assert result["description"] == "orders 테이블의 데이터를 관리합니다."
    assert result["method"] == "offline-rules"
