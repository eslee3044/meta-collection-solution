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


def test_ollama_table_description_uses_local_provider(monkeypatch):
    import json
    from app.ai_description import suggest_table_description

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({"description": "주문 정보를 관리하는 테이블"})}).encode()

    monkeypatch.setattr("app.ai_description.urlopen", lambda *args, **kwargs: Response())
    result = suggest_table_description("orders", [{"column_name": "order_id", "data_type": "INTEGER"}], "ollama")

    assert result["description"] == "주문 정보를 관리하는 테이블"
    assert result["method"] == "local-ollama"


def test_rules_generate_table_description():
    from app.ai_description import suggest_table_description

    result = suggest_table_description("orders", [{"column_name": "order_id", "data_type": "INTEGER"}], "rules")

    assert result["description"] == "orders 테이블의 데이터를 관리합니다."
    assert result["method"] == "offline-rules"


def test_column_prompt_includes_full_table_context(monkeypatch):
    import json

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({"CUSTOMER_ID": ["주문 고객 식별자"]})}).encode()

    def fake_urlopen(request, **kwargs):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("app.ai_description.urlopen", fake_urlopen)
    result = suggest_descriptions(
        [{"column_name": "CUSTOMER_ID", "data_type": "INTEGER", "comments": ""}],
        provider="ollama",
        table_name="orders",
        table_columns=[
            {"column_name": "ID", "data_type": "INTEGER", "pk_yn": "Y"},
            {"column_name": "CUSTOMER_ID", "data_type": "INTEGER"},
            {"column_name": "ORDERED_AT", "data_type": "TIMESTAMP"},
        ],
    )

    prompt = captured["payload"]["prompt"]
    assert "table_columns" in prompt
    assert "ORDERED_AT" in prompt
    assert '"targets"' in prompt
    assert result[0]["method"] == "local-ollama"
    assert result[0]["context_column_count"] == 3




def test_column_ollama_request_requires_every_target_in_json_schema(monkeypatch):
    import json

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({
                "OPER": ["작업 식별 정보"],
                "ACTIVE": ["활성 여부"],
            })}).encode()

    def fake_urlopen(request, **kwargs):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("app.ai_description.urlopen", fake_urlopen)
    result = suggest_descriptions([
        {"column_name": "OPER", "data_type": "NUMBER", "comments": ""},
        {"column_name": "ACTIVE", "data_type": "CHAR", "comments": ""},
    ], provider="ollama", table_name="WLM_CLASSIFIER_PLAN")

    schema = captured["payload"]["format"]
    assert schema["type"] == "object"
    assert schema["required"] == ["OPER", "ACTIVE"]
    assert set(schema["properties"]) == {"OPER", "ACTIVE"}
    assert [item["method"] for item in result] == ["local-ollama", "local-ollama"]



def test_date_column_recommendation_falls_back_to_rules(monkeypatch):
    from app.ai_description import recommend_date_columns

    monkeypatch.setattr("app.ai_description.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    result = recommend_date_columns("orders", [
        {"column_name": "created_at", "data_type": "TIMESTAMP"},
        {"column_name": "updated_at", "data_type": "TIMESTAMP"},
    ], provider="ollama")

    assert result["method"] == "offline-rules"
    assert result["partition_columns"] == ["created_at"]
    assert result["update_base_columns"] == ["updated_at"]


def test_date_column_recommendation_accepts_only_real_columns(monkeypatch):
    import json
    from app.ai_description import recommend_date_columns

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({"response": json.dumps({"partition_columns": ["not_real"], "update_base_columns": ["updated_at"]})}).encode()

    monkeypatch.setattr("app.ai_description.urlopen", lambda *args, **kwargs: Response())
    result = recommend_date_columns("orders", [{"column_name": "updated_at", "data_type": "TIMESTAMP"}], provider="ollama")
    assert result["method"] == "local-ollama"
    assert result["partition_columns"] == ["updated_at"]
    assert result["update_base_columns"] == ["updated_at"]


def test_rules_id_uses_table_context():
    result = suggest_descriptions(
        [{"column_name": "id", "data_type": "INTEGER", "comments": ""}],
        provider="rules",
        table_name="orders",
        table_columns=[
            {"column_name": "id", "data_type": "INTEGER", "pk_yn": "Y"},
            {"column_name": "customer_id", "data_type": "INTEGER"},
            {"column_name": "ordered_at", "data_type": "TIMESTAMP"},
        ],
    )
    assert result[0]["description"] == "orders 레코드를 식별하는 고유 식별자"
    assert result[0]["context_column_count"] == 3
