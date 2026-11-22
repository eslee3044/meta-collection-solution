import ast
import json

from app.airflow_dag_factory import render_dag_source


def test_rendered_dag_is_valid_python_and_contains_manifest_identity():
    source = render_dag_source({"dag_id": "mv_init_demo_1", "schedule": "manual", "plan_fingerprint": "abc", "tasks": ["check_source", "load_chunks"]})
    ast.parse(source)
    assert "mv_init_demo_1" in source
    assert "abc" in source
    assert "check_source" in source


def test_rendered_dag_does_not_embed_credentials():
    source = render_dag_source({"dag_id": "mv_init_demo_1", "schedule": "manual", "plan_fingerprint": "abc", "tasks": ["load_chunks"], "password": "should-not-appear"})
    compile(source, "generated.py", "exec")
    assert "json.loads" in source
    assert "password" not in source.lower()
