import { useEffect, useMemo, useState } from 'react'
import { Activity, ChevronDown, ExternalLink, Play, RefreshCw, Search } from 'lucide-react'
import { api, fmt } from './api'

type ScheduleItem = any

const stateLabel: Record<string, string> = {
  success: '성공', failed: '실패', running: '실행 중', queued: '대기 중', scheduled: '예약됨', skipped: '건너뜀', upstream_failed: '선행 실패', None: '미실행',
}
const stateClass = (state?: string | null) => state === 'success' ? 'success' : state === 'failed' || state === 'upstream_failed' ? 'error' : state === 'running' || state === 'queued' ? 'pending' : 'neutral'

export default function DatalakeScheduleStatusPage({ toast }: { toast: (message: string) => void }) {
  const [mode, setMode] = useState('MANIFEST_ONLY')
  const [timezone, setTimezone] = useState('Asia/Seoul')
  const [airflowUrl, setAirflowUrl] = useState('http://localhost:8085')
  const [items, setItems] = useState<ScheduleItem[]>([])
  const [query, setQuery] = useState('')
  const [stateFilter, setStateFilter] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const openAirflow = (path = '') => window.open(`${airflowUrl.replace(/\/$/, '')}${path}`, '_blank', 'noopener,noreferrer')

  const load = async (quiet = false) => {
    try {
      const result = await api<any>('/api/datalake-load/schedule-status')
      setMode(result.mode || 'MANIFEST_ONLY'); setTimezone(result.timezone || 'Asia/Seoul'); setAirflowUrl(result.airflow_url || 'http://localhost:8085'); setItems(result.items || [])
      if (!quiet) toast('적재 스케줄과 Airflow 처리상태를 새로고침했습니다.')
    } catch (error) { toast((error as Error).message) }
  }
  useEffect(() => { void load(true); const timer = window.setInterval(() => void load(true), 15000); return () => window.clearInterval(timer) }, [])

  const filtered = useMemo(() => items.filter(item => {
    const latest = item.runs?.[0]?.state || 'None'
    const text = `${item.system_cd} ${item.instance_name} ${item.owner} ${item.table_name} ${item.dag_id}`.toLowerCase()
    return text.includes(query.toLowerCase()) && (stateFilter === 'all' || latest === stateFilter)
  }), [items, query, stateFilter])
  const counts = useMemo(() => ({ total: items.length, deployed: items.filter(item => item.dag_status === 'DEPLOYED').length, running: items.filter(item => ['queued', 'running'].includes(item.runs?.[0]?.state)).length, failed: items.filter(item => ['failed', 'upstream_failed'].includes(item.runs?.[0]?.state)).length }), [items])

  const runInitial = async (item: ScheduleItem) => {
    setBusy(true)
    try { const result = await api<any>(`/api/datalake-load/plans/${item.plan_id}/airflow-run`, { method: 'POST' }); toast(`초기 적재 실행을 요청했습니다. (${result.state || 'queued'})`); await load(true) }
    catch (error) { toast((error as Error).message) } finally { setBusy(false) }
  }

  return <>
    <header className="page-head"><div><p className="eyebrow">AUTOMATION</p><h1>적재 스케줄·처리상태 <span className="load-mode-badge">{mode === 'AIRFLOW_MANAGED' ? 'Airflow 직접 운영' : 'Manifest 수동 운영'}</span></h1><p>적재 계획의 DAG 배포·스케줄·최근 실행과 task 처리상태를 한 화면에서 확인합니다. 기준 시간대: {timezone}</p></div><div className="source-actions"><button className="ghost" onClick={() => openAirflow()}><ExternalLink size={16}/>Airflow 관리자</button><button className="ghost" onClick={() => void load()} disabled={busy}><RefreshCw size={16}/>새로고침</button></div></header>
    <div className="schedule-kpis"><div><span>관리 DAG</span><b>{counts.total}</b></div><div><span>배포 완료</span><b>{counts.deployed}</b></div><div><span>실행 중·대기</span><b>{counts.running}</b></div><div><span>최근 실패</span><b className={counts.failed ? 'danger-text' : ''}>{counts.failed}</b></div></div>
    <section className="panel schedule-status-panel"><div className="toolbar"><div><h3>적재 DAG 처리상태</h3><p>15초마다 자동 갱신 · 최근 5회 실행과 최신 실행의 task를 표시합니다.</p></div><div className="schedule-filters"><div className="search"><Search size={16}/><input aria-label="적재 스케줄 검색" placeholder="시스템·테이블·DAG 검색" value={query} onChange={event => setQuery(event.target.value)}/></div><select aria-label="Airflow 실행 상태 필터" value={stateFilter} onChange={event => setStateFilter(event.target.value)}><option value="all">전체 상태</option><option value="queued">대기 중</option><option value="running">실행 중</option><option value="success">성공</option><option value="failed">실패</option></select></div></div>{mode !== 'AIRFLOW_MANAGED' && <div className="schedule-empty"><Activity size={22}/><b>Airflow 직접 운영 모드가 아닙니다.</b><span>시스템 관리에서 Airflow 직접 운영으로 전환하면 DAG 스케줄과 실행상태를 조회할 수 있습니다.</span></div>}{mode === 'AIRFLOW_MANAGED' && <div className="schedule-table"><div className="schedule-table-head"><span>대상</span><span>DAG / 유형</span><span>스케줄</span><span>배포</span><span>최근 실행</span><span>작업</span></div>{filtered.map(item => { const latest = item.runs?.[0]; const key = `${item.plan_id}-${item.dag_type}`; const isOpen = expanded === key; return <div className="schedule-record" key={key}><div className="schedule-row"><span><b>{item.owner}.{item.table_name}</b><small>{item.system_cd} · {item.instance_name}</small></span><span><code>{item.dag_id}</code><small>{item.dag_type === 'INIT' ? '초기 적재' : '증분 적재'}</small></span><span>{item.schedule || '수동 실행'}<small>{item.incremental_status === 'READY' ? '증분 준비됨' : '증분 잠김'}</small></span><span><i className={`status-dot ${item.dag_status === 'DEPLOYED' ? 'ok' : 'wait'}`}/>{item.dag_status}<small>{fmt(item.deployed_at)}</small></span><span><b className={`load-status ${stateClass(latest?.state)}`}>{stateLabel[latest?.state || 'None']}</b><small>{latest ? fmt(latest.execution_date || latest.start_date) : '실행 기록 없음'}</small></span><span className="schedule-actions"><button className="ghost compact" onClick={() => setExpanded(isOpen ? null : key)}><ChevronDown size={14} className={isOpen ? 'rotate-180' : ''}/>상세</button>{item.airflow_dag && <button className="ghost compact" onClick={() => openAirflow(`/dags/${encodeURIComponent(item.dag_id)}/grid`)}><ExternalLink size={13}/>Airflow Grid</button>}{item.dag_type === 'INIT' && item.dag_status === 'DEPLOYED' && <button className="primary compact" onClick={() => void runInitial(item)} disabled={busy}><Play size={13}/>초기 실행</button>}</span></div>{isOpen && <div className="schedule-detail"><div><b>최근 실행 이력</b>{item.runs?.length ? item.runs.map((run: any) => <span key={run.dag_run_id}><em className={`load-status ${stateClass(run.state)}`}>{stateLabel[run.state] || run.state}</em>{run.dag_run_id}<small>{fmt(run.execution_date || run.start_date)}{run.end_date ? ` · 종료 ${fmt(run.end_date)}` : ''}</small></span>) : <p>실행 기록이 없습니다.</p>}</div><div><b>최신 task 처리상태</b>{item.tasks?.length ? item.tasks.map((task: any) => <span key={task.task_id}><em className={`load-status ${stateClass(task.state)}`}>{stateLabel[task.state] || task.state}</em>{task.task_id}<small>{task.try_number ? `시도 ${task.try_number}` : ''}{task.operator ? ` · ${task.operator}` : ''}</small></span>) : <p>최신 실행의 task 정보가 없습니다.</p>}</div></div>}</div>})}{!filtered.length && <div className="schedule-empty"><Activity size={22}/><b>조건에 맞는 적재 DAG가 없습니다.</b><span>검색어 또는 실행 상태 필터를 확인하세요.</span></div>}</div>}</section>
  </>
}
