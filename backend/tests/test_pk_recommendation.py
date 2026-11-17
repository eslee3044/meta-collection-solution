import json
from urllib.error import URLError

from app.pk_recommendation import candidate_fingerprint, deterministic_pk_candidates, parse_candidate_columns, recommend_pk_candidates


def table(columns, **extra):
    return {"name": "fact_order_line", "columns": columns, **extra}


def col(name, nullable=False, typ="INTEGER"):
    return {"name": name, "nullable": nullable, "data_type": typ}


def test_source_pk_has_precedence_and_no_candidates():
    result = recommend_pk_candidates(table([col("id")], primary_key={"constrained_columns": ["id"]}), "ollama", "x")
    assert result["source_pk_applied"] and result["candidates"] == []


def test_unique_constraint_then_index():
    result = deterministic_pk_candidates(table([col("a"), col("b"), col("ORDER_NO"), col("LINE_NO")], unique_constraints=[{"columns": ["a", "b"]}], unique_indexes=[{"columns": ["ORDER_NO"]}]))
    assert result[0]["columns"] == ["a", "b"]
    assert result[1]["columns"] == ["ORDER_NO"]


def test_order_line_and_weak_columns():
    result = deterministic_pk_candidates(table([col("ORDER_NO"), col("LINE_NO"), col("AMOUNT"), col("COMMENT", typ="TEXT")]))
    assert ["ORDER_NO", "LINE_NO"] in [x["columns"] for x in result]
    assert all("AMOUNT" not in x["columns"] and "COMMENT" not in x["columns"] for x in result)


def test_json_columns_and_fingerprint_are_bounded_and_deterministic():
    assert parse_candidate_columns(json.dumps(["A", "B"])) == ["A", "B"]
    try:
        parse_candidate_columns(["A"] * 2)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicates must fail")
    assert candidate_fingerprint("S", "I", "", "O", "T", 1, ["A", "B"]) == candidate_fingerprint("S", "I", "", "O", "T", 1, ["A", "B"])


def test_ollama_invalid_or_disabled_falls_back(monkeypatch):
    monkeypatch.setattr("app.pk_recommendation.urlopen", lambda *a, **k: (_ for _ in ()).throw(URLError("offline")))
    result = recommend_pk_candidates(table([col("ORDER_NO"), col("LINE_NO")]), "ollama", "x")
    assert result["method"] == "offline-rules" and result["fallback_used"]
    assert recommend_pk_candidates(table([col("ORDER_NO")]), "rules", "x")["method"] == "offline-rules"


def test_ollama_rejects_fabricated_columns_and_prompt_is_metadata_only(monkeypatch):
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({"response": json.dumps({"candidates": [{"columns": ["not_a_column"], "confidence": .99}]})}).encode()
    def fake(request, timeout):
        captured["prompt"] = request.data.decode()
        return Response()
    monkeypatch.setattr("app.pk_recommendation.urlopen", fake)
    result = recommend_pk_candidates(table([col("ORDER_NO")]), "ollama", "x")
    assert result["fallback_used"]
    assert "password" in captured["prompt"].lower() and "row values" in captured["prompt"]
    assert "secret_value" not in captured["prompt"]


def test_ollama_non_local_url_and_malformed_response_fall_back(monkeypatch):
    monkeypatch.setenv("METAVAULT_LOCAL_AI_URL", "https://example.com")
    result = recommend_pk_candidates(table([col("ORDER_NO")]), "ollama", "x")
    assert result["method"] == "offline-rules"
    monkeypatch.setenv("METAVAULT_LOCAL_AI_URL", "http://localhost:11434")
    monkeypatch.setattr("app.pk_recommendation.urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert recommend_pk_candidates(table([col("ORDER_NO")]), "ollama", "x")["fallback_used"]
