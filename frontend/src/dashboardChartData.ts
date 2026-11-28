export type SystemCount = { name: string; count: number }
export type AirflowHistory = { status: string; daily?: Record<string, number>; systems?: SystemCount[] }
export type CollectionDay = { date: string; table_count: number; view_count: number }

export function chartDays(days: CollectionDay[], airflow?: AirflowHistory) {
  return days.map(day => ({ date: day.date, metadata: day.table_count + day.view_count,
    airflow: airflow?.status === 'AVAILABLE' ? airflow.daily?.[day.date] ?? 0 : null }))
}

export function systemSlices(rows: SystemCount[]) {
  const sorted = rows.filter(row => row.count > 0).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
  const total = sorted.reduce((sum, row) => sum + row.count, 0)
  const slices = sorted.slice(0, 5)
  if (sorted.length > 5) slices.push({ name: '기타', count: sorted.slice(5).reduce((sum, row) => sum + row.count, 0) })
  return { total, slices }
}
