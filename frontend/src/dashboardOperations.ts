export type DashboardActivity = {
  source: 'metadata' | 'datalake' | 'airflow'
  activity_type: 'collection' | 'load_plan' | 'initial_load' | 'incremental_load'
  target: string
  status: string
  updated_at?: string | null
  detail?: string | null
  initial_status?: string
  incremental_status?: string
}

type StatusCounts = Record<string, number>

export type DashboardOperations = {
  sources?: number
  active_jobs?: number
  objects?: number
  failed_runs?: number
  layout_changes_pending?: number
  recent_runs?: Array<{ id?: number; job_id?: number; status?: string; started_at?: string; finished_at?: string | null }>

  orchestration?: { mode?: string; airflow_status?: string; timezone?: string } | null
  datalake_summary?: {
    plans_total?: number; dags_total?: number; dags_deployed?: number
    init_dags_total?: number; init_dags_deployed?: number
    run_status?: 'NO_DAGS' | 'NO_RUNS' | 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
    latest_running_or_queued_dags?: number | null; latest_failed_dags?: number | null
    initial_status_counts?: StatusCounts; incremental_status_counts?: StatusCounts
    recent_activity?: DashboardActivity[]
  } | null
  operations_activity?: DashboardActivity[]
}

export type DashboardRefreshState = { data: DashboardOperations | null; refreshedAt: string | null; loading: boolean; error: boolean }
type RefreshEvent = { type: 'start' | 'failure' } | { type: 'success'; data: DashboardOperations; at: string }

export function dashboardRefresh(state: DashboardRefreshState, event: RefreshEvent): DashboardRefreshState {
  if (event.type === 'success') return { data: event.data, refreshedAt: event.at, loading: false, error: false }
  if (event.type === 'start') return { ...state, loading: true }
  return { ...state, loading: false, error: true }
}

export function dashboardActivity(data: DashboardOperations, canReadLoad: boolean) {
  if (data.operations_activity) return data.operations_activity.filter(item => canReadLoad || item.source === 'metadata').slice(0, 8)
  const rows = (data.recent_runs ?? []).map((run): DashboardActivity => ({
    source: 'metadata', activity_type: 'collection', target: run.job_id == null ? '수집 작업' : `수집 작업 #${run.job_id}`,
    status: run.status ?? '', updated_at: run.finished_at ?? run.started_at,
  }))
  if (canReadLoad) rows.push(...(data.datalake_summary?.recent_activity ?? []))
  const priority = (status: string) => {
    const key = status.toLowerCase()
    if (['failed', 'upstream_failed', 'blocked', 'timeout'].includes(key)) return 0
    if (['running', 'queued', 'not_deployed'].includes(key)) return 1
    return 2
  }
  const time = (item: DashboardActivity) => Date.parse(item.updated_at ?? '') || 0
  return rows.sort((a, b) => priority(a.initial_status ?? a.status) - priority(b.initial_status ?? b.status) || time(b) - time(a)).slice(0, 8)
}

export function dashboardActivityDetails(item: DashboardActivity) {
  const types = { collection: '메타 수집', load_plan: '적재 계획', initial_load: '초기 적재', incremental_load: '증분 적재' }
  const statuses: Record<string, string> = { success: '성공', succeeded: '성공', completed: '완료', running: '실행 중', queued: '대기', failed: '실패', upstream_failed: '선행 실패', ready: '준비', planned: '계획', blocked: '차단', cancelled: '취소됨', cancel_requested: '취소 요청', timeout: '시간 초과', not_deployed: '미배포' }
  const key = item.status.toLowerCase()
  const initial = item.initial_status?.toLowerCase()
  const incremental: Record<string, string> = { LOCKED: '초기 적재 전', READY: '증분 설정 가능', SCHEDULE_ACTIVE: '증분 스케줄 활성', SCHEDULE_PENDING_DEPLOYMENT: '증분 DAG 배포 대기' }
  const schedule = item.incremental_status
  const detail = item.detail || [initial && Object.hasOwn(statuses, initial) ? `초기 적재 ${statuses[initial]}` : '', schedule && Object.hasOwn(incremental, schedule) ? incremental[schedule] : ''].filter(Boolean).join(' · ')
  return { type: types[item.activity_type] ?? '운영 활동', key, status: Object.hasOwn(statuses, key) ? statuses[key] : '확인 필요', detail }
}

export function dashboardTime(value?: string | null, timeZone?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  const options = { dateStyle: 'short', timeStyle: 'short' } as const
  try { return new Intl.DateTimeFormat('ko-KR', { ...options, timeZone }).format(date) }
  catch { return new Intl.DateTimeFormat('ko-KR', { ...options, timeZone: 'UTC' }).format(date) }
}

export function airflowLabel(summary: DashboardOperations) {
  if (summary.orchestration?.mode === 'MANIFEST_ONLY') return 'Manifest 수동 운영'
  if (summary.orchestration?.mode === 'AIRFLOW_MANAGED') return 'Airflow 직접 운영'
  return '운영 모드 미확인'
}

export function dashboardRunMetrics(summary: DashboardOperations) {
  const load = summary.datalake_summary
  const mode = summary.orchestration?.mode
  const status = summary.orchestration?.airflow_status
  const unknown = (label: string) => ({ label, failed: null, running: null })
  if (!load) return unknown('적재 요약 없음')
  if (mode === 'MANIFEST_ONLY' || status === 'NOT_APPLICABLE' || load.run_status === 'NOT_APPLICABLE') return unknown('Airflow 미연동')
  if (load.run_status === 'NO_DAGS') return unknown('DAG 없음')
  if (status === 'UNAVAILABLE' || load.run_status === 'UNAVAILABLE') return unknown('Airflow 상태 확인 불가')
  if (load.run_status === 'NO_RUNS') return unknown('실행 이력 없음')
  if (mode !== 'AIRFLOW_MANAGED' || status !== 'AVAILABLE' || load.run_status !== 'AVAILABLE') return unknown('실행 상태 미확인')
  return { label: 'DAG별 최신 실행 기준', failed: load.latest_failed_dags ?? null, running: load.latest_running_or_queued_dags ?? null }
}

type FlowState = { tone: 'neutral' | 'done' | 'attention'; label: string }
const flow = (label: string, tone: FlowState['tone'] = 'neutral'): FlowState => ({ label, tone })

export function dashboardMetadataFlow(data: DashboardOperations) {
  const latest = data.recent_runs?.[0]?.status?.toLowerCase()
  const pending = data.layout_changes_pending
  return {
    snapshot: latest === 'success' ? flow('최근 수집 성공', 'done')
      : latest === 'failed' ? flow('최근 수집 실패', 'attention')
      : latest === 'running' ? flow('수집 중', 'attention')
      : latest === 'queued' ? flow('실행 대기', 'attention')
      : data.recent_runs?.length === 0 ? flow('실행 이력 없음') : flow('확인 필요'),
    diff: pending != null && pending > 0 ? flow(`${pending}건 검토 필요`, 'attention') : flow('비교 결과 확인 필요'),
    review: pending === 0 ? flow('대기 없음') : pending != null && pending > 0 ? flow('검토 필요', 'attention') : flow('확인 필요'),
    apply: flow('반영 결과 확인 필요'),
  }
}

function countState(counts: StatusCounts | undefined, labels: Record<string, string>, done: string[], attention: string[], total?: number) {
  const entries = Object.entries(counts ?? {}).filter(([, count]) => count > 0)
  if (!entries.length) return flow(total === 0 ? '계획 없음' : '확인 필요')
  const known = Object.hasOwn
  return flow(entries.map(([key, count]) => `${known(labels, key) ? labels[key] : '미확인'} ${count}`).join(' · '),
    entries.some(([key]) => attention.includes(key)) ? 'attention'
      : entries.every(([key]) => done.includes(key)) && entries.reduce((sum, [, count]) => sum + count, 0) === total ? 'done' : 'neutral')
}

export function dashboardLoadFlow(data: DashboardOperations) {
  const load = data.datalake_summary
  const total = load?.plans_total
  const initial = load?.initial_status_counts
  const dagTotal = load?.init_dags_total
  const deployed = load?.init_dags_deployed
  const manifest = data.orchestration?.mode === 'MANIFEST_ONLY'
  const initialLabels = { PLANNED: '계획', RUNNING: '진행 중', COMPLETED: '완료', FAILED: '실패', BLOCKED: '차단' }
  return {
    plan: total === 0 ? flow('계획 없음') : total == null ? flow('확인 필요') : flow(`${total}개 계획`, 'done'),
    prepare: countState(initial, initialLabels, ['PLANNED', 'RUNNING', 'COMPLETED'], ['FAILED', 'BLOCKED'], total),
    dag: manifest ? flow('Airflow 미연동') : dagTotal === 0 ? flow('INIT DAG 없음')
      : deployed != null && dagTotal != null ? flow(`${deployed}/${dagTotal}개 배포`, deployed === dagTotal ? 'done' : 'attention') : flow('확인 필요'),
    initial: countState(initial, initialLabels, ['COMPLETED'], ['FAILED', 'BLOCKED'], total),
    incremental: countState(load?.incremental_status_counts, { LOCKED: '초기 적재 전', READY: '설정 가능', SCHEDULE_ACTIVE: '활성', SCHEDULE_PENDING_DEPLOYMENT: '배포 대기' }, manifest ? [] : ['SCHEDULE_ACTIVE'], ['SCHEDULE_PENDING_DEPLOYMENT'], total),
  }
}
