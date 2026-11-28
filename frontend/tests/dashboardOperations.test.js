import assert from 'node:assert/strict'
import test from 'node:test'
import * as dashboard from '../src/dashboardOperations.ts'

const available = { orchestration: { mode: 'AIRFLOW_MANAGED', airflow_status: 'AVAILABLE' } }

test('missing mode does not indicate direct operation', () => {
  assert.equal(dashboard.airflowLabel({}), '운영 모드 미확인')
})

test('only available run summaries can show numeric KPIs, including a real zero', () => {
  for (const state of ['NO_DAGS', 'NO_RUNS', 'UNAVAILABLE', 'NOT_APPLICABLE', undefined]) {
    const model = dashboard.dashboardRunMetrics({ ...available, datalake_summary: { run_status: state, latest_failed_dags: 0 } })
    assert.equal(model.failed, null)
    assert.equal(model.running, null)
    assert.ok(model.label)
  }
  assert.equal(dashboard.dashboardRunMetrics(available).label, '적재 요약 없음')
  const model = dashboard.dashboardRunMetrics({ ...available, datalake_summary: { run_status: 'AVAILABLE', latest_failed_dags: 0, latest_running_or_queued_dags: 2 } })
  assert.deepEqual([model.failed, model.running], [0, 2])
  assert.equal(dashboard.dashboardRunMetrics({ orchestration: { mode: 'MANIFEST_ONLY' }, datalake_summary: { run_status: 'AVAILABLE', latest_failed_dags: 0 } }).failed, null)
})

test('load flow uses explicit plan and INIT DAG evidence, not global run counts or connectivity', () => {
  const base = { plans_total: 2, dags_total: 3, dags_deployed: 3, init_dags_total: 2, init_dags_deployed: 1, run_status: 'AVAILABLE', latest_running_or_queued_dags: 0, latest_failed_dags: 0 }
  const missing = dashboard.dashboardLoadFlow({ ...available, datalake_summary: base })
  assert.notEqual(missing.initial.tone, 'done')
  assert.notEqual(missing.incremental.tone, 'done')
  assert.equal(missing.dag.label, '1/2개 배포')
  assert.notEqual(missing.dag.tone, 'done')
  const actual = dashboard.dashboardLoadFlow({ ...available, datalake_summary: { ...base, initial_status_counts: { COMPLETED: 1, FAILED: 1 }, incremental_status_counts: { SCHEDULE_ACTIVE: 1, SCHEDULE_PENDING_DEPLOYMENT: 1 } } })
  assert.match(actual.initial.label, /완료 1.*실패 1/)
  assert.equal(actual.initial.tone, 'attention')
  assert.match(actual.incremental.label, /활성 1.*배포 대기 1/)
  assert.equal(actual.incremental.tone, 'attention')
})

test('metadata flow does not infer comparison, approval or apply from absent evidence', () => {
  const missing = dashboard.dashboardMetadataFlow({ objects: 500 })
  assert.equal(missing.review.label, '확인 필요')
  const failed = dashboard.dashboardMetadataFlow({ recent_runs: [{ status: 'failed' }, { status: 'success' }], layout_changes_pending: 0, objects: 500 })
  assert.equal(failed.snapshot.label, '최근 수집 실패')
  assert.notEqual(failed.diff.label, '변경 없음')
  assert.deepEqual(failed.review, { tone: 'neutral', label: '대기 없음' })
  assert.notEqual(failed.apply.tone, 'done')
})

test('refresh preserves last successful data and timestamp after a failure', () => {
  const initial = { data: null, refreshedAt: null, loading: true, error: false }
  assert.deepEqual(dashboard.dashboardRefresh(initial, { type: 'failure' }), { ...initial, loading: false, error: true })
  const data = { sources: 4 }
  const success = dashboard.dashboardRefresh(initial, { type: 'success', data, at: '2026-11-28T03:00:00Z' })
  const refreshing = dashboard.dashboardRefresh(success, { type: 'start' })
  assert.equal(refreshing.loading, true)
  assert.equal(refreshing.data, data)
  assert.deepEqual(dashboard.dashboardRefresh(refreshing, { type: 'failure' }), { data, refreshedAt: '2026-11-28T03:00:00Z', loading: false, error: true })
})

test('combined activity preserves API ordering and hides load rows without permission', () => {
  const metadata = { source: 'metadata', activity_type: 'collection', status: 'failed' }
  const airflow = { source: 'airflow', activity_type: 'initial_load', status: 'queued' }
  const data = { operations_activity: [airflow, metadata] }
  assert.deepEqual(dashboard.dashboardActivity(data, false), [metadata])
  assert.deepEqual(dashboard.dashboardActivity(data, true), [airflow, metadata])
  assert.equal(dashboard.dashboardActivity({ operations_activity: Array(12).fill(metadata) }, true).length, 8)
  assert.equal(dashboard.dashboardActivityDetails(airflow).type, '초기 적재')
  assert.equal(dashboard.dashboardActivityDetails(metadata).status, '실패')
})

test('legacy dashboard payload still shows both metadata and authorized load activity', () => {
  const plan = { source: 'datalake', activity_type: 'load_plan', target: 'SYS.ORDERS', status: 'READY', initial_status: 'COMPLETED', incremental_status: 'LOCKED', updated_at: '2026-11-28T17:00:00Z' }
  const data = { recent_runs: [{ job_id: 4, status: 'failed', started_at: '2026-11-28T12:00:00Z' }], datalake_summary: { recent_activity: [plan] } }
  assert.deepEqual(dashboard.dashboardActivity(data, true).map(row => row.source), ['metadata', 'datalake'])
  assert.deepEqual(dashboard.dashboardActivity(data, false).map(row => row.source), ['metadata'])
  assert.equal(dashboard.dashboardActivityDetails(plan).detail, '초기 적재 완료 · 초기 적재 전')
})

test('activity dates use configured timezone and fall back safely', () => {
  assert.equal(dashboard.dashboardTime('invalid', 'Asia/Seoul'), '—')
  const utc = dashboard.dashboardTime('2026-11-28T03:00:00Z', 'UTC')
  assert.notEqual(dashboard.dashboardTime('2026-11-28T03:00:00Z', 'Asia/Seoul'), utc)
  assert.equal(dashboard.dashboardTime('2026-11-28T03:00:00Z', 'Invalid/Zone'), utc)
})
