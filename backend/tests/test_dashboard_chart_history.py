from datetime import datetime, timezone
from http.client import IncompleteRead
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import airflow_control


def test_success_history_uses_completion_window_and_paginates(monkeypatch):
    calls = []

    def request(method, path, payload, *, timeout):
        calls.append((method, path, payload))
        offset = payload['page_offset']
        return 200, {'total_entries': 2, 'dag_runs': [{'dag_id': 'managed', 'dag_run_id': str(offset)}]}

    monkeypatch.setattr(airflow_control, '_request', request)
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 1, tzinfo=timezone.utc)
    rows = airflow_control.dashboard_successful_runs(('managed',), start, end)
    assert [x['dag_run_id'] for x in rows] == ['0', '1']
    assert all(method == 'POST' and path == 'dags/~/dagRuns/list' for method, path, _ in calls)
    assert calls[0][2]['dag_ids'] == ['managed']
    assert calls[0][2]['states'] == ['success']
    assert calls[0][2]['end_date_gte'] == start.isoformat()
    assert calls[0][2]['end_date_lte'] == end.isoformat()


def test_history_can_read_more_than_twenty_pages(monkeypatch):
    def request(method, path, payload, *, timeout):
        start = payload['page_offset']
        return 200, {'total_entries': 2001, 'dag_runs': [{'id': i} for i in range(start, min(start + 100, 2001))]}

    monkeypatch.setattr(airflow_control, '_request', request)
    now = datetime.now(timezone.utc)
    assert len(airflow_control.dashboard_successful_runs(('managed',), now, now)) == 2001


def test_truncated_history_response_is_an_upstream_failure(monkeypatch):
    def request(*args, **kwargs):
        raise IncompleteRead(b'partial')

    monkeypatch.setattr(airflow_control, '_request', request)
    now = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as exc:
        airflow_control.dashboard_successful_runs(('managed',), now, now)
    assert exc.value.status_code == 502


def test_chart_excludes_placeholder_dags(monkeypatch):
    from app import main

    user = SimpleNamespace(roles=[SimpleNamespace(permissions=[SimpleNamespace(code='jobs:read')])])
    session = SimpleNamespace(execute=lambda stmt: iter([
        ('placeholder', 'A', '{"tasks":["load_chunks"]}'),
        ('real', 'B', '{"tasks":["load_chunks"],"executor":"METAVAULT_API_FULL_LOAD"}'),
    ]))
    monkeypatch.setattr(main, '_orchestration_config', lambda session: SimpleNamespace(mode='AIRFLOW_MANAGED'))

    def history(dag_ids, start, end):
        assert dag_ids == ('real',)
        return [{'dag_id': 'real', 'dag_run_id': 'r1', 'state': 'success', 'end_date': '2026-11-02T00:00:00Z'}]

    monkeypatch.setattr(main, 'dashboard_successful_runs', history)
    start, end = (datetime(2026, 11, day, tzinfo=timezone.utc) for day in (1, 3))
    result = main._dashboard_airflow_chart(session, start, end, timezone.utc, user)
    assert result == {'status': 'AVAILABLE', 'daily': {'2026-11-02': 1}, 'systems': [{'name': 'B', 'count': 1}]}
