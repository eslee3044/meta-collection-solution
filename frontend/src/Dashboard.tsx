import { useEffect, useReducer, useRef, useState } from 'react'
import { Activity, ArrowRight, Bell, CalendarClock, CircleAlert, Database, GitCompare, Info, Play, Plus, RefreshCw, ShieldCheck, Split, TableProperties, Upload } from 'lucide-react'
import { api } from './api'
import DashboardCharts from './DashboardCharts'
import { airflowLabel, dashboardActivity, dashboardActivityDetails, dashboardLoadFlow, dashboardMetadataFlow, dashboardRefresh, dashboardRunMetrics, dashboardTime, type DashboardOperations } from './dashboardOperations'

type Destination = 'sources' | 'jobs' | 'metadata' | 'registered' | 'loadOperations' | 'loadSchedule' | 'system'
type Props = {
  go: (page: Destination) => void
  goJobsWithStatus: (status: string) => void
  onOpenChanges: () => void
  canReadLoad: boolean
  canOpenSystem: boolean

}
type Card = { label: string; value?: number | string | null; unit?: string; Icon: typeof Database; color: string; description?: string; link: string; onClick: () => void; missing?: string }
type Step = { title: string; Icon: typeof Database; page: Destination; state: { label: string; tone: string } }

function DashboardCards({ cards }: { cards: Card[] }) {
  const [open, setOpen] = useState<string | null>(null)
  return <div className="stats dashboard-stats">{cards.map(({ label, value, unit, Icon, color, description, link, onClick, missing }) => <div key={label} className="dashboard-stat-wrap">
    <button type="button" className="stat-card stat-card-link" onClick={onClick}>
      <span className={`stat-icon ${color}`}><Icon size={21} aria-hidden="true"/></span>
      <span className="stat-card-content"><span className="dashboard-stat-label">{label}</span>
        <strong className={value == null ? 'dashboard-stat-missing' : undefined}>{value == null ? missing ?? '—' : value.toLocaleString('ko-KR')}{value != null && unit && <small>{unit}</small>}</strong>
        <span className="stat-card-link-label">{link}<ArrowRight size={13} aria-hidden="true"/></span>
      </span>
    </button>
    {description && <button type="button" className={`stat-card-info ${open === label ? 'is-open' : ''}`} aria-label={`${label} 설명`} aria-describedby={`dashboard-tip-${color}`} aria-expanded={open === label} onClick={() => setOpen(open === label ? null : label)} onKeyDown={event => { if (event.key === 'Escape') setOpen(null) }}>
      <Info size={16} aria-hidden="true"/><span className="stat-card-tooltip" id={`dashboard-tip-${color}`} role="tooltip">{description}</span>
    </button>}
  </div>)}</div>
}

function FlowLane({ title, items, go }: { title: string; items: Step[]; go: Props['go'] }) {
  return <div><h3>{title}</h3><div className={`dashboard-flow ${items.length === 5 ? 'dashboard-flow-load' : ''}`} aria-label={title}>
    {items.map(({ title, Icon, page, state }, index) => <div className="dashboard-flow-item" key={title}>
      <button type="button" className={`dashboard-flow-node ${state.tone}`} onClick={() => go(page)}>
        <span className="dashboard-flow-number" aria-hidden="true">{index + 1}</span><span className="dashboard-flow-icon"><Icon size={18} aria-hidden="true"/></span>
        <span className="dashboard-flow-copy"><b>{title}</b><em>{state.label}</em></span>
      </button>
    </div>)}
  </div></div>
}

export default function Dashboard({ go, goJobsWithStatus, onOpenChanges, canReadLoad, canOpenSystem }: Props) {
  const [request, dispatch] = useReducer(dashboardRefresh, { data: null, refreshedAt: null, loading: true, error: false })
  const active = useRef<AbortController | null>(null)
  const refresh = async () => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    dispatch({ type: 'start' })
    try {
      const data = await api<DashboardOperations>('/api/dashboard', { signal: controller.signal })
      if (!controller.signal.aborted) dispatch({ type: 'success', data, at: new Date().toISOString() })
    } catch {
      if (!controller.signal.aborted) dispatch({ type: 'failure' })
    }
  }
  useEffect(() => {
    const reload = () => { void refresh() }
    reload()
    window.addEventListener('metavault:layout-change-updated', reload)
    return () => { active.current?.abort(); window.removeEventListener('metavault:layout-change-updated', reload) }
  }, [])

  const data = request.data ?? {}
  const pending = data.layout_changes_pending ?? 0
  const load = canReadLoad ? data.datalake_summary : null
  const ops = dashboardRunMetrics(data)
  const timeZone = canReadLoad ? data.orchestration?.timezone : undefined
  const meta = dashboardMetadataFlow(data)
  const loadFlow = dashboardLoadFlow(data)
  const activity = dashboardActivity(data, Boolean(load))
  const undeployed = load?.dags_total != null && load.dags_deployed != null ? load.dags_total - load.dags_deployed : 0
  const knownCount = (count: number | undefined, positive: string, empty: string) => ({ label: count == null ? '확인 필요' : count > 0 ? positive : empty, tone: count != null && count > 0 ? 'done' : 'neutral' })
  const view = (page: Destination) => () => go(page)
  const scope = request.data ? ops.label : request.error ? '조회 실패' : '불러오는 중'
  const metadataCards: Card[] = [
    { label: '등록 데이터 소스', value: data.sources, unit: '개', Icon: Database, color: 'blue', description: '등록된 DB 연결과 연결 상태를 확인합니다.', link: 'DB 연결 관리 보기', onClick: view('sources') },
    { label: '활성 수집 작업', value: data.active_jobs, unit: '개', Icon: CalendarClock, color: 'violet', description: '현재 활성화된 수집 스케줄과 최근 실행 결과를 확인합니다.', link: '수집 작업 보기', onClick: view('jobs') },
    { label: '누적 수집 객체', value: data.objects, unit: '개', Icon: TableProperties, color: 'mint', description: '성공한 수집 실행에서 확인된 메타 객체 누적 건수입니다.', link: '수집 결과 보기', onClick: view('metadata') },
    { label: '실패한 수집 실행', value: data.failed_runs, unit: '건', Icon: CircleAlert, color: 'coral', description: '전체 수집 이력에서 실패한 실행의 누적 건수입니다.', link: '실행 이력 보기', onClick: () => goJobsWithStatus('failed') },
  ]
  const loadCards: Card[] = [
    { label: '적재 계획', value: load?.plans_total, unit: '개', Icon: Split, color: 'blue', link: '적재 운영 보기', onClick: view('loadOperations') },
    { label: 'DAG 배포', value: load?.dags_deployed != null && load.dags_total != null ? `${load.dags_deployed.toLocaleString('ko-KR')}/${load.dags_total.toLocaleString('ko-KR')}` : null, Icon: Upload, color: 'violet', link: '처리 상태 보기', onClick: view('loadSchedule') },
    { label: '실행 중·대기', value: ops.running, missing: ops.label === 'DAG별 최신 실행 기준' ? '확인 필요' : ops.label, unit: '개', Icon: Play, color: 'mint', link: '실행 상태 보기', onClick: view('loadSchedule') },
    { label: '최신 실패 DAG', value: ops.failed, missing: ops.label === 'DAG별 최신 실행 기준' ? '확인 필요' : ops.label, unit: '개', Icon: CircleAlert, color: 'coral', link: '실패 상태 보기', onClick: view('loadSchedule') },
  ]
  return <div className="dashboard-overview">
    <header className="page-head"><div><p className="eyebrow">OVERVIEW</p><h1>데이터 운영 현황</h1><p>메타 수집과 Datalake 적재 운영 상태를 한눈에 확인하세요.</p></div>
      <div className="dashboard-head-actions"><button type="button" className="ghost" disabled={request.loading} onClick={() => void refresh()}><RefreshCw size={16} aria-hidden="true"/>{request.loading ? '갱신 중…' : '새로고침'}</button><button type="button" className="primary" onClick={view('sources')}><Plus size={17} aria-hidden="true"/>DB 연결 추가</button></div>
    </header>
    <div className="dashboard-context" role="status">
      {canReadLoad && request.data && <span className="dashboard-mode">{airflowLabel(data)}{timeZone && ` · ${timeZone}`}</span>}
      {request.refreshedAt ? <span>마지막 갱신 <time dateTime={request.refreshedAt}>{dashboardTime(request.refreshedAt, timeZone)}</time></span> : request.loading && <span>운영 현황을 불러오는 중입니다.</span>}
    </div>
    {request.error && <div className="layout-alert-banner has-alert" role="alert"><CircleAlert size={20} aria-hidden="true"/><div><strong>{request.data ? '갱신 실패 · 마지막으로 확인한 데이터 표시 중' : '운영 현황을 불러오지 못했습니다.'}</strong></div><button type="button" className="ghost" disabled={request.loading} onClick={() => void refresh()}>다시 시도</button></div>}
    {pending > 0 && <div className="layout-alert-banner has-alert" role="status"><div className="layout-alert-icon"><Bell size={20} aria-hidden="true"/><b>{pending}</b></div><div><strong>처리할 메타 구조 변경 {pending}건</strong><p>원천 Snapshot에서 감지된 변경을 검토하세요.</p></div><button type="button" className="ghost" onClick={onOpenChanges}>변경 검토 <ArrowRight size={15} aria-hidden="true"/></button></div>}
    {load && (Boolean(ops.failed) || undeployed > 0 || ops.label === 'Airflow 상태 확인 불가') && <div className="layout-alert-banner has-alert" role="status"><div className="layout-alert-icon"><Activity size={20} aria-hidden="true"/></div><div><strong>{[ops.failed ? `최신 실패 DAG ${ops.failed}건` : '', undeployed > 0 ? `미배포 DAG ${undeployed}개` : '', ops.label === 'Airflow 상태 확인 불가' ? ops.label : ''].filter(Boolean).join(' · ')}</strong><p>적재 스케줄 및 실행 이력을 확인하세요.</p></div><button type="button" className="ghost" onClick={view('loadSchedule')}>적재 상태 보기 <ArrowRight size={15} aria-hidden="true"/></button></div>}
    <section aria-labelledby="dashboard-metadata"><h2 id="dashboard-metadata">메타 수집</h2><DashboardCards cards={metadataCards}/></section>
    <section aria-labelledby="dashboard-load"><h2 id="dashboard-load">Datalake 적재 · Airflow</h2>
      {load ? <><p className="dashboard-section-note">{scope}{ops.label === 'DAG별 최신 실행 기준' && ' · 실패 및 선행 실패를 집계합니다.'}{ops.label === 'Airflow 미연동' && canOpenSystem && <> · <button type="button" className="ghost" onClick={view('system')}>시스템 관리</button></>}</p><DashboardCards cards={loadCards}/></>
        : <p className="dashboard-section-note">{!canReadLoad ? '적재 운영 현황을 볼 권한이 없습니다.' : request.data ? '적재 요약을 사용할 수 없습니다.' : scope}</p>}
    </section>
    <section className="panel dashboard-flow-panel" aria-labelledby="dashboard-flow"><div className="panel-head"><div><h2 id="dashboard-flow">운영 흐름</h2><p>메타 수집과 Datalake 적재의 다음 행동을 분리해 확인합니다.</p></div></div>
      <div className="dashboard-flow-lanes"><FlowLane title="메타 수집·반영" go={go} items={[
        { title: 'DB 연결', Icon: Database, page: 'sources', state: knownCount(data.sources, '연결 등록됨', '등록 필요') },
        { title: '수집 스케줄', Icon: CalendarClock, page: 'jobs', state: knownCount(data.active_jobs, '활성', '설정 필요') },
        { title: 'Snapshot 수집', Icon: RefreshCw, page: 'metadata', state: meta.snapshot },
        { title: '구조 변경 비교', Icon: GitCompare, page: 'metadata', state: meta.diff },
        { title: '승인·반려', Icon: ShieldCheck, page: 'registered', state: meta.review },
        { title: '메타 반영·조회', Icon: TableProperties, page: 'registered', state: meta.apply },
      ]}/>{load && <FlowLane title="Datalake 적재 · Airflow" go={go} items={[
        { title: '적재 계획', Icon: Split, page: 'loadOperations', state: loadFlow.plan },
        { title: '초기 적재 준비', Icon: TableProperties, page: 'loadOperations', state: loadFlow.prepare },
        { title: 'INIT DAG 배포', Icon: Upload, page: 'loadSchedule', state: loadFlow.dag },
        { title: '초기 적재 완료', Icon: Play, page: 'loadSchedule', state: loadFlow.initial },
        { title: '증분 스케줄 활성화', Icon: CalendarClock, page: 'loadSchedule', state: loadFlow.incremental },
      ]}/>}</div>
    </section>
    <DashboardCharts canReadLoad={canReadLoad} refreshKey={request.refreshedAt}/>
    <section className="panel dashboard-activity-panel" aria-labelledby="dashboard-activity"><div className="panel-head"><div><h2 id="dashboard-activity">최근 운영 활동</h2><p>{load ? '메타 수집, 적재 계획 및 Airflow 실행 요약입니다.' : '메타 수집 실행 요약입니다.'}</p></div>{load && <button type="button" className="ghost" onClick={view('loadSchedule')}>적재 상태 전체 보기 <ArrowRight size={14} aria-hidden="true"/></button>}</div>
      {activity.length ? <div className="dashboard-activity-list">{activity.map((item, index) => {
        const { type, key, status, detail } = dashboardActivityDetails(item)
        return <button type="button" className="dashboard-activity-row" key={`${item.source}-${item.target}-${item.updated_at}-${index}`} onClick={view(item.source === 'metadata' ? 'jobs' : item.source === 'airflow' ? 'loadSchedule' : 'loadOperations')}>
          <span className="activity-main"><b title={item.target}>{item.target}</b><time dateTime={item.updated_at ?? undefined}>{dashboardTime(item.updated_at, timeZone)}</time>{detail && <small>{detail}</small>}</span><span className="dashboard-activity-type">{type}</span><span className="dashboard-activity-status"><i className={`activity-dot activity-${key}`} aria-hidden="true"/>{status}</span><ArrowRight size={15} aria-hidden="true"/>
        </button>
      })}</div> : <p className="dashboard-section-note dashboard-activity-empty">{request.data ? '표시할 최근 운영 활동이 없습니다.' : request.error ? '활동을 불러오지 못했습니다.' : '활동을 불러오는 중입니다.'}</p>}
    </section>

  </div>
}
