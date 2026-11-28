import test from 'node:test'
import assert from 'node:assert/strict'
import { chartDays, systemSlices } from '../src/dashboardChartData.ts'

test('joins tables and views into one series and keeps unknown Airflow values distinct from zero', () => {
  const days = [{ date: '2026-11-27', table_count: 4, view_count: 3 }, { date: '2026-11-28', table_count: 0, view_count: 1 }]
  assert.deepEqual(chartDays(days, { status: 'AVAILABLE', daily: { '2026-11-28': 2 } }), [
    { date: '2026-11-27', metadata: 7, airflow: 0 }, { date: '2026-11-28', metadata: 1, airflow: 2 },
  ])
  assert.equal(chartDays(days, { status: 'UNAVAILABLE' })[0].airflow, null)
})

test('system shares retain totals when grouping the long tail', () => {
  const rows = Array.from({ length: 8 }, (_, i) => ({ name: `SYS${i}`, count: i + 1 }))
  const { total, slices } = systemSlices(rows)
  assert.equal(total, 36)
  assert.equal(slices.at(-1).name, '기타')
  assert.equal(slices.at(-1).count, 6)
  assert.equal(slices.reduce((sum, item) => sum + item.count, 0), 36)
  assert.deepEqual(systemSlices([{ name: 'Empty', count: 0 }]), { total: 0, slices: [] })
})
