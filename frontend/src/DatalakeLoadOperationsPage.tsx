import { useEffect, useState } from 'react'
import { Activity, Database, Download, FileCode2, Play, Plus, RefreshCw, Search, Split, X } from 'lucide-react'
import { api } from './api'

type LoadPlan = any
const strategies = [['SINGLE', '단일 적재'], ['SOURCE_PARTITION', '원천 파티션'], ['DATE_RANGE', '날짜 범위'], ['PK_RANGE', 'PK 범위'], ['COMPOSITE', '날짜 + PK 복합']]
const modes = [['INIT', '초기 적재'], ['INCREMENTAL', '증분 적재']]
const askLoadConfirm = (message: string) => new Promise<boolean>(resolve => window.dispatchEvent(new CustomEvent('metavault:confirm', { detail: { title: 'AI 추천값 적용 확인', message, confirmLabel: '추천값 적용', danger: false, resolve } })))

const copyLoadPrompt = async (text: string) => {
  if (!text) throw new Error('복사할 내용이 없습니다.')
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return }
    catch { /* DOM fallback */ }
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.readOnly = true
  textarea.setAttribute('aria-hidden', 'true')
  Object.assign(textarea.style, { position: 'fixed', left: '0', top: '0', width: '1px', height: '1px', opacity: '0' })
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, text.length)
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('브라우저가 텍스트 복사를 허용하지 않았습니다.')
}

export default function DatalakeLoadOperationsPage({ toast }: { toast: (message: string) => void }) {
  const [plans, setPlans] = useState<LoadPlan[]>([])
  const [selected, setSelected] = useState<LoadPlan | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [registered, setRegistered] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [sourceQuery, setSourceQuery] = useState('')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [planPage, setPlanPage] = useState(1)
  const [planPageSize, setPlanPageSize] = useState(25)
  const [tablePickerQuery, setTablePickerQuery] = useState('')
  const [prefilledTable, setPrefilledTable] = useState<any | null>(null)
  const [expandedSourceKeys, setExpandedSourceKeys] = useState<string[]>([])
  const [recommendProgress, setRecommendProgress] = useState<{ open: boolean; stage: number; error?: string; recommendation?: any; manualPrompt?: string; manualResponse?: string; manualValidation?: any }>({ open: false, stage: 0 })
  const [manualResponse, setManualResponse] = useState('')
  const [aiConfig, setAiConfig] = useState<any>({ description_ai_enabled: false, description_ai_provider: 'rules' })
  const [orchestrationMode, setOrchestrationMode] = useState<'MANIFEST_ONLY'|'AIRFLOW_MANAGED'>('MANIFEST_ONLY')
  const [form, setForm] = useState<any>({ load_mode: 'INIT', split_strategy: 'SINGLE', estimated_rows: '', estimated_bytes: '', target_chunk_rows: 1000000, max_parallelism: 1, pool_slots: 2, credential_mode: 'metadata', source_pool: '', allowed_window: '' })

  const load = async () => { const [planRows, metadata, config] = await Promise.all([api<any[]>('/api/datalake-load/plans'), api<any>('/api/metadata/registered'), api<any>('/api/meta-table-config')]); setPlans(planRows || []); setRegistered(metadata?.items || metadata || []); setAiConfig(config || { description_ai_enabled: false, description_ai_provider: 'rules' }) }
  useEffect(() => { void api<any>('/api/system-settings/datalake-orchestration').then(config => setOrchestrationMode(config?.mode === 'AIRFLOW_MANAGED' ? 'AIRFLOW_MANAGED' : 'MANIFEST_ONLY')).catch(() => undefined) }, [])
  const openDetail = async (plan: LoadPlan) => { setSelected(plan); setDetail(await api<any>(`/api/datalake-load/plans/${plan.id}`)) }
  const openCreateForTable = (item: any) => { const identity = `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}`; setSelected(null); setTablePickerQuery(''); setExpandedSourceKeys([]); setPrefilledTable(item); setForm((current: any) => ({ ...current, identity })); setOpen(true) }
  const openCreateEmpty = () => { setPrefilledTable(null); setTablePickerQuery(''); setExpandedSourceKeys([]); setForm((current: any) => ({ ...current, identity: '' })); setOpen(true) }
  useEffect(() => { void load().catch(error => toast((error as Error).message)) }, [])

  const recommendPlan = async () => {
    const table = registered.find(item => `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}` === form.identity)
    if (!table) { toast('먼저 등록 메타 테이블을 선택하세요.'); return }
    setBusy(true); setRecommendProgress({ open: true, stage: 0 })
    try {
      const identity = { system_cd: table.system_cd, instance_name: table.instance_name, postfix: table.postfix || '', owner: table.owner, table_name: table.table_name }
      setRecommendProgress({ open: true, stage: 1 })
      await new Promise(resolve => window.setTimeout(resolve, 180))
      setRecommendProgress({ open: true, stage: 2 })
      const result = await api<any>('/api/datalake-load/recommend', { method: 'POST', body: JSON.stringify({ ...identity, estimated_rows: form.estimated_rows === '' ? null : Number(form.estimated_rows), estimated_bytes: form.estimated_bytes === '' ? null : Number(form.estimated_bytes) }) })
      setRecommendProgress({ open: true, stage: 3 })
      const recommendation = result.recommendation
      await new Promise(resolve => window.setTimeout(resolve, 220))
      setRecommendProgress({ open: true, stage: 4, recommendation })
      setRecommendProgress({ open: true, stage: 5, recommendation })
    } catch (error) { setRecommendProgress({ open: true, stage: -1, error: (error as Error).message }); toast((error as Error).message) } finally { setBusy(false) }
  }

  const openManualRecommendation = async () => {
    const table = registered.find(item => `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}` === form.identity)
    if (!table) return
    setBusy(true)
    setManualResponse('')
    try {
      const identity = { system_cd: table.system_cd, instance_name: table.instance_name, postfix: table.postfix || '', owner: table.owner, table_name: table.table_name }
      const result = await api<any>('/api/datalake-load/recommend/manual-prompt', { method: 'POST', body: JSON.stringify({ ...identity, estimated_rows: form.estimated_rows === '' ? null : Number(form.estimated_rows), estimated_bytes: form.estimated_bytes === '' ? null : Number(form.estimated_bytes), pool_slots: Number(form.pool_slots), max_parallelism_allowed: 32 }) })
      setRecommendProgress(current => ({ ...current, open: true, stage: 5, error: undefined, manualPrompt: result.prompt, manualResponse: '' }))
    } catch (error) { setRecommendProgress(current => ({ ...current, open: true, stage: -1, error: (error as Error).message })); toast((error as Error).message) } finally { setBusy(false) }
  }

  const validateManualRecommendation = async () => {
    const table = registered.find(item => `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}` === form.identity)
    if (!table || !manualResponse.trim()) { toast('AI 응답 JSON을 붙여넣어 주세요.'); return }
    setBusy(true)
    try {
      const identity = { system_cd: table.system_cd, instance_name: table.instance_name, postfix: table.postfix || '', owner: table.owner, table_name: table.table_name }
      const result = await api<any>('/api/datalake-load/recommend/manual-validate', { method: 'POST', body: JSON.stringify({ ...identity, estimated_rows: form.estimated_rows === '' ? null : Number(form.estimated_rows), estimated_bytes: form.estimated_bytes === '' ? null : Number(form.estimated_bytes), pool_slots: Number(form.pool_slots), max_parallelism_allowed: 32, response_text: manualResponse }) })
      setRecommendProgress(current => ({ ...current, open: true, stage: 5, error: undefined, recommendation: result.recommendation, manualValidation: result.validation }))
    } catch (error) { setRecommendProgress(current => ({ ...current, open: true, stage: -1, error: (error as Error).message })); toast((error as Error).message) } finally { setBusy(false) }
  }

  const copyManualRecommendationPrompt = async () => {
    if (!recommendProgress.manualPrompt) return
    try { await copyLoadPrompt(recommendProgress.manualPrompt); toast('적재 추천 프롬프트를 복사했습니다. 승인된 AI에서 실행한 뒤 JSON 응답을 붙여넣으세요.') } catch (error) { toast((error as Error).message || '복사에 실패했습니다. 프롬프트 영역을 직접 선택해 복사하세요.') }
  }

  const copyManifest = async (dag: any) => {
    try {
      await copyLoadPrompt(JSON.stringify(dag.manifest, null, 2))
      toast(`${dag.dag_type} manifest를 클립보드에 복사했습니다.`)
    } catch (error) {
      toast((error as Error).message || 'manifest 복사에 실패했습니다. JSON을 직접 선택해 복사하세요.')
    }
  }

  const prepareRuntime = async () => {
    const table = registered.find(item => `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}` === form.identity)
    if (!table) { toast('먼저 등록 메타 테이블을 선택하세요.'); return }
    setBusy(true)
    try {
      const identity = { system_cd: table.system_cd, instance_name: table.instance_name, postfix: table.postfix || '', owner: table.owner, table_name: table.table_name }
      const result = await api<any>('/api/datalake-load/source-runtime/prepare', { method: 'POST', body: JSON.stringify({ ...identity, pool_slots: Number(form.pool_slots), credential_mode: form.credential_mode, confirm_pool_resize: false }) })
      if (result.status === 'CONFIRM_REQUIRED') {
        const accepted = await askLoadConfirm(`원천 Pool 슬롯 변경\n\nPool: ${result.pool_name}\n현재 슬롯: ${result.current_slots}\n요청 슬롯: ${result.requested_slots}\n\n슬롯 수를 변경할까요?`)
        if (accepted) await api('/api/datalake-load/source-runtime/prepare', { method: 'POST', body: JSON.stringify({ ...identity, pool_slots: Number(form.pool_slots), credential_mode: form.credential_mode, confirm_pool_resize: true }) })
        else { toast('원천 Pool 슬롯 변경을 취소했습니다.'); return }
      }
      setForm((current: any) => ({ ...current, source_pool: result.pool_name || current.source_pool }))
      toast(`원천 DB Connection과 Pool을 ${result.status === 'READY' ? '준비했습니다' : '확인했습니다'}.`)
    } catch (error) { toast((error as Error).message) } finally { setBusy(false) }
  }

  const createPlan = async (event: React.FormEvent) => {
    event.preventDefault()
    const table = registered.find(item => `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}` === form.identity)
    if (!table) { toast('등록 메타 테이블을 선택하세요.'); return }
    setBusy(true)
    try {
      const result = await api<any>('/api/datalake-load/plans', { method: 'POST', body: JSON.stringify({ ...table, load_mode: form.load_mode, split_strategy: form.split_strategy, estimated_rows: form.estimated_rows === '' ? null : Number(form.estimated_rows), estimated_bytes: form.estimated_bytes === '' ? null : Number(form.estimated_bytes), target_chunk_rows: Number(form.target_chunk_rows), max_parallelism: Number(form.max_parallelism), source_pool: form.source_pool || null, allowed_window: form.allowed_window || null }) })
      toast(result.status === 'EXISTING' ? '같은 적재 계획이 이미 있습니다.' : '적재 계획과 Chunk를 생성했습니다.'); setOpen(false); await load(); if (result.id) { const plan = (await api<any[]>('/api/datalake-load/plans')).find(item => item.id === result.id); if (plan) await openDetail(plan) }
    } catch (error) { toast((error as Error).message) } finally { setBusy(false) }
  }
  const createDags = async () => { if (!selected) return; setBusy(true); try { await api(`/api/datalake-load/plans/${selected.id}/dags`, { method: 'POST' }); toast('초기/증분 DAG manifest를 생성했습니다.'); await openDetail(selected); await load() } catch (error) { toast((error as Error).message) } finally { setBusy(false) } }
  const updateChunk = async (chunk: any, status: string) => { if (!selected) return; try { await api(`/api/datalake-load/plans/${selected.id}/chunks/${chunk.id}`, { method: 'PATCH', body: JSON.stringify({ status, source_rows: chunk.source_rows, staging_rows: chunk.staging_rows, validation_status: status === 'SUCCEEDED' ? 'PASSED' : null }) }); const fresh = await api<any>(`/api/datalake-load/plans/${selected.id}`); setDetail(fresh); toast(`Chunk ${chunk.chunk_no} 상태를 ${status}로 변경했습니다.`); await load() } catch (error) { toast((error as Error).message) } }
  const sourceOptions = Array.from(new Set(registered.map(item => item.instance_name || item.system_cd || '원천 DB 미지정'))).filter(source => source.toLowerCase().includes(sourceQuery.trim().toLowerCase())).sort((a, b) => a.localeCompare(b, 'ko'))
  const filtered = registered.filter(item => (sourceFilter === 'all' || (item.instance_name || item.system_cd || '원천 DB 미지정') === sourceFilter) && `${item.system_cd} ${item.instance_name || ''} ${item.owner} ${item.table_name}`.toLowerCase().includes(query.toLowerCase()))
  const planForTable = (item: any) => plans.find(plan => plan.system_cd === item.system_cd && plan.instance_name === item.instance_name && plan.owner === item.owner && plan.table_name === item.table_name)
  const planPageCount = Math.max(1, Math.ceil(filtered.length / planPageSize))
  const pagedPlans = filtered.slice((planPage - 1) * planPageSize, planPage * planPageSize)
  useEffect(() => { setPlanPage(1) }, [query, sourceFilter, planPageSize])
  useEffect(() => { if (planPage > planPageCount) setPlanPage(planPageCount) }, [planPage, planPageCount])
  const selectedIdentity = form.identity || ''
  const normalizedPickerQuery = tablePickerQuery.trim().toLowerCase()
  const sourceGroupMap = new Map<string, { sourceName: string; items: any[] }>()
  registered.forEach((item: any) => {
    const sourceName = item.etl_conn_nm || item.instance_name || item.system_cd || '원천 DB 미지정'
    const searchText = `${sourceName} ${item.system_cd || ''} ${item.instance_name || ''} ${item.owner || ''} ${item.table_name || ''}`.toLowerCase()
    if (!normalizedPickerQuery || searchText.includes(normalizedPickerQuery)) {
      const key = `${item.system_cd || ''}|${item.instance_name || ''}|${item.etl_conn_nm || ''}`
      const group: { sourceName: string; items: any[] } = sourceGroupMap.get(key) || { sourceName, items: [] }
      group.items.push(item)
      sourceGroupMap.set(key, group)
    }
  })
  const sourceGroups: { sourceName: string; items: any[] }[] = [...sourceGroupMap.values()] as { sourceName: string; items: any[] }[]
  sourceGroups.sort((a: { sourceName: string }, b: { sourceName: string }) => a.sourceName.localeCompare(b.sourceName, 'ko'))

  return <><header className="page-head"><div><p className="eyebrow">DATA MANAGEMENT</p><h1>Datalake 적재 운영 <span className="load-mode-badge">{orchestrationMode === 'AIRFLOW_MANAGED' ? 'Airflow 직접 운영' : 'Manifest 수동 운영'}</span></h1><p>초기·증분 적재 계획, Chunk 체크포인트와 DAG manifest를 관리합니다.</p></div><div className="source-actions"><button className="ghost" onClick={() => void load()}><RefreshCw size={16}/>새로고침</button><button className="primary" onClick={openCreateEmpty}><Plus size={17}/>적재 설계 만들기</button></div></header><div className="load-operations-layout"><aside className="panel load-source-list"><h3>데이터 소스</h3><div className="search"><Search size={16}/><input aria-label="원천 DB 검색" placeholder="원천 DB 검색" value={sourceQuery} onChange={event => setSourceQuery(event.target.value)}/></div><button type="button" className={`load-source-row ${sourceFilter === 'all' ? 'selected' : ''}`} onClick={() => setSourceFilter('all')}><Database size={17}/><span>전체 원천 DB</span><b>{registered.length}</b></button>{sourceOptions.map(source => <button type="button" key={source} className={`load-source-row ${sourceFilter === source ? 'selected' : ''}`} onClick={() => setSourceFilter(source)}><Database size={17}/><span>{source}</span><b>{registered.filter(item => (item.instance_name || item.system_cd || '원천 DB 미지정') === source).length}</b></button>)}</aside><section className="panel load-plan-list"><div className="toolbar"><div><h3>등록 테이블</h3><p>{filtered.length}개 테이블 · 계획 {filtered.filter(item => Boolean(planForTable(item))).length}개</p></div><div className="load-list-controls"><div className="search"><Search size={16}/><input placeholder="원천 DB, 시스템, OWNER, 테이블 검색" value={query} onChange={event => setQuery(event.target.value)}/></div></div></div>{pagedPlans.map(item => { const plan = planForTable(item); const identity = `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}`; return <button type="button" className={`load-plan-row ${plan && selected?.id === plan.id ? 'selected' : ''}`} key={identity} onClick={() => plan ? void openDetail(plan) : openCreateForTable(item)}><span className="load-plan-icon"><Database size={17}/></span><span><b>{item.owner}.{item.table_name}</b><small>{item.system_cd} · {plan ? `${plan.load_mode === 'INIT' ? '초기 적재' : '증분 적재'} · ${plan.split_strategy}` : '적재 계획 미생성'}</small></span><span className={`load-status ${plan?.initial_status === 'COMPLETED' ? 'success' : plan ? 'pending' : 'unplanned'}`}>{plan ? (plan.initial_status === 'PLANNED' ? '계획됨' : plan.initial_status === 'COMPLETED' ? '초기 완료' : plan.initial_status) : '계획 만들기'}</span></button>})}<div className="pagination load-pagination"><label>페이지당 표시 <select aria-label="적재 운영 페이지당 표시 개수" value={planPageSize} onChange={event => { setPlanPageSize(Number(event.target.value)); setPlanPage(1) }}><option value={25}>25개</option><option value={50}>50개</option><option value={100}>100개</option><option value={200}>200개</option></select></label><button type="button" className="ghost" disabled={planPage <= 1} onClick={() => setPlanPage(1)}>처음</button><button type="button" className="ghost" disabled={planPage <= 1} onClick={() => setPlanPage(Math.max(1, Math.floor((planPage - 1) / 5) * 5))}>이전</button>{Array.from({ length: Math.min(Math.max(1, planPageCount), 5) }, (_, index) => Math.floor((Math.max(1, planPage) - 1) / 5) * 5 + 1 + index).filter(number => number <= Math.max(1, planPageCount)).map(number => <button type="button" className={number === planPage ? 'page-number active' : 'page-number'} key={number} aria-current={number === planPage ? 'page' : undefined} onClick={() => setPlanPage(number)}>{number}</button>)}<button type="button" className="ghost" disabled={planPage >= planPageCount} onClick={() => setPlanPage(Math.min(Math.max(1, planPageCount), Math.floor((planPage - 1) / 5) * 5 + 6))}>다음</button><button type="button" className="ghost" disabled={planPage >= planPageCount} onClick={() => setPlanPage(Math.max(1, planPageCount))}>끝</button></div></section>{detail ? <div className="modal-backdrop plan-detail-backdrop" role="dialog" aria-modal="true" onMouseDown={event => { if (event.target === event.currentTarget) { setDetail(null); setSelected(null) } }}><section className="panel load-plan-detail plan-detail-popup"><div className="toolbar"><div><p className="eyebrow">LOAD PLAN #{detail.plan.id}</p><h2>{detail.plan.owner}.{detail.plan.table_name}</h2><p>{detail.plan.system_cd} · 계획 fingerprint {detail.plan.plan_fingerprint}</p></div><button className="ghost" onClick={() => { setDetail(null); setSelected(null) }}><X size={16}/>닫기</button></div><div className="load-summary-grid"><div><span>적재 방식</span><b>{detail.plan.load_mode === 'INIT' ? '초기 적재' : '증분 적재'}</b></div><div><span>분할 방식</span><b>{strategies.find(item => item[0] === detail.plan.split_strategy)?.[1]}</b></div><div><span>예상 행 수</span><b>{detail.plan.estimated_rows?.toLocaleString() || '측정 전'}</b></div><div><span>최대 병렬도</span><b>{detail.plan.max_parallelism}개</b></div></div><div className="load-tabs"><b>적재 개요</b><b>초기 적재 계획</b><b>DAG 구성</b><b>실행 현황</b><b>증분 적재</b></div><div className="load-actions"><button className="primary" onClick={() => void createDags()} disabled={busy}><FileCode2 size={16}/>DAG manifest 생성</button>{detail.dags?.map((dag: any) => <button className="ghost" key={dag.dag_id} onClick={() => void copyManifest(dag)}><Download size={16}/>{dag.dag_type} manifest 복사</button>)}</div><h3><Activity size={17}/>Chunk 실행 현황</h3><div className="chunk-table"><div className="chunk-head"><span>Chunk</span><span>예상 행 수</span><span>체크포인트</span><span>상태</span><span>작업</span></div>{detail.chunks.map((chunk: any) => <div className="chunk-row" key={chunk.id}><span>#{String(chunk.chunk_no).padStart(4, '0')}</span><span>{chunk.expected_rows?.toLocaleString() || '측정 전'}</span><span>{chunk.checkpoint_at ? '완료 기록됨' : '미완료'}</span><span className={`load-status ${chunk.status === 'SUCCEEDED' ? 'success' : chunk.status === 'FAILED' ? 'error' : 'pending'}`}>{chunk.status}</span><span>{chunk.status !== 'SUCCEEDED' && <button className="ghost compact" onClick={() => void updateChunk(chunk, 'SUCCEEDED')}><Play size={13}/>성공 처리</button>}{chunk.status === 'FAILED' && <button className="ghost compact" onClick={() => void updateChunk(chunk, 'PENDING')}>재개</button>}</span></div>)}</div></section></div> : null}</div>{open && <div className="modal-backdrop" role="dialog" aria-modal="true"><form className="modal load-plan-modal" onSubmit={createPlan}><div className="modal-head"><div><h2>적재 설계 만들기</h2><p>등록 메타를 기준으로 초기·증분 적재 계획과 Chunk를 생성합니다.</p></div><button type="button" className="ghost" onClick={() => setOpen(false)}><X size={16}/></button></div><div className="table-picker">{!prefilledTable && <div className="table-picker-search"><Search size={15}/><input aria-label="원천 DB·테이블 검색" placeholder="원천 DB 또는 테이블 검색" value={tablePickerQuery} onChange={event => setTablePickerQuery(event.target.value)}/>{tablePickerQuery && <button type="button" onClick={() => setTablePickerQuery('')} aria-label="검색어 지우기"><X size={14}/></button>}</div>}{prefilledTable ? <div className="selected-table-summary"><div><span>선택된 테이블</span><b>{prefilledTable.owner}.{prefilledTable.table_name}</b><small>{prefilledTable.system_cd} · {prefilledTable.instance_name}</small></div></div> : <div className="table-picker-tree" role="tree">{sourceGroups.map((group, index) => { const sourceKey = `${group.sourceName}|${index}`; const expanded = normalizedPickerQuery.length > 0 || expandedSourceKeys.includes(sourceKey); return <div className="table-tree-group" key={sourceKey}><button type="button" className="table-tree-source" onClick={() => setExpandedSourceKeys(current => current.includes(sourceKey) ? current.filter(key => key !== sourceKey) : [...current, sourceKey])} aria-expanded={expanded}><span className="tree-toggle">{expanded ? '−' : '+'}</span><Database size={15}/><b>{group.sourceName}</b><small>{group.items.length}</small></button>{expanded && <div className="table-tree-items">{group.items.map(item => { const identity = `${item.system_cd}|${item.instance_name}|${item.postfix || ''}|${item.owner}|${item.table_name}`; return <button type="button" role="treeitem" className="table-tree-item" key={identity} onClick={() => { setForm((current: any) => ({ ...current, identity })); setPrefilledTable(item) }}><span>{item.owner}.{item.table_name}</span><small>{item.system_cd}</small></button>})}</div>}</div>})}{!sourceGroups.length && <p className="table-picker-empty">검색 조건에 맞는 원천 DB·테이블이 없습니다.</p>}</div>}</div><div className="ai-recommend-box"><div><b>AI 적재 설계 추천</b><small>등록 메타의 PK·날짜 컬럼과 예상 규모를 분석해 분할·Chunk·병렬도를 추천합니다. 추천 실패 시 규칙 기반으로 자동 전환합니다.</small></div>{aiConfig.description_ai_enabled && aiConfig.description_ai_provider === 'manual' ? <button type="button" className="ghost" onClick={() => void openManualRecommendation()} disabled={busy}>프롬프트 복사·응답 가져오기</button> : <button type="button" className="ghost" onClick={() => void recommendPlan()} disabled={busy}><Activity size={15}/>{aiConfig.description_ai_enabled && aiConfig.description_ai_provider === 'ollama' ? 'AI로 추천' : '규칙 기반 추천'}</button>}</div><div className="source-runtime-box"><div><b>원천 DB 실행 환경</b><small>메타 수집 계정을 기본으로 사용해 Airflow Connection과 원천 Pool을 자동 준비합니다.</small></div><div className="runtime-controls"><select value={form.credential_mode} onChange={event => setForm({ ...form, credential_mode: event.target.value })}><option value="metadata">메타 수집 계정</option><option value="dedicated">별도 적재 계정</option></select>{form.credential_mode === 'dedicated' && <><input value={form.dedicated_username || ''} onChange={event => setForm({ ...form, dedicated_username: event.target.value })} placeholder="적재 계정"/><input type="password" value={form.dedicated_password || ''} onChange={event => setForm({ ...form, dedicated_password: event.target.value })} placeholder="비밀번호"/></>}<input type="number" min="1" max="32" value={form.pool_slots} onChange={event => setForm({ ...form, pool_slots: event.target.value })} aria-label="원천 Pool 슬롯"/><button type="button" className="ghost" onClick={() => void prepareRuntime()} disabled={busy}><Database size={15}/>Connection·Pool 자동 준비</button></div></div><div className="form-grid"><label><span className="field-label">적재 방식<button type="button" className="field-help" aria-label="적재 방식 설명" data-tooltip="초기 적재는 전체 데이터를 처음 적재하고, 증분 적재는 변경분을 주기적으로 적재합니다.">?</button></span><select value={form.load_mode} onChange={event => setForm({ ...form, load_mode: event.target.value })}>{modes.map(item => <option value={item[0]} key={item[0]}>{item[1]}</option>)}</select></label><label><span className="field-label">분할 방식<button type="button" className="field-help" aria-label="분할 방식 설명" data-tooltip="단일 적재는 한 번에 처리하고, 키·범위·해시 분할은 여러 Chunk로 나누어 처리합니다.">?</button></span><select value={form.split_strategy} onChange={event => setForm({ ...form, split_strategy: event.target.value })}>{strategies.map(item => <option value={item[0]} key={item[0]}>{item[1]}</option>)}</select></label><label title="원천 테이블에서 적재할 것으로 예상되는 행 수입니다.">예상 행 수<input type="number" min="0" value={form.estimated_rows} onChange={event => setForm({ ...form, estimated_rows: event.target.value })} placeholder="미측정"/></label><label title="원천 테이블에서 적재할 것으로 예상되는 데이터 용량입니다.">예상 용량(bytes)<input type="number" min="0" value={form.estimated_bytes} onChange={event => setForm({ ...form, estimated_bytes: event.target.value })} placeholder="미측정"/></label><label title="한 번의 Chunk 작업에서 처리할 목표 행 수입니다.">Chunk 목표 행 수<input type="number" min="1" value={form.target_chunk_rows} onChange={event => setForm({ ...form, target_chunk_rows: event.target.value })}/></label><label title="동시에 실행할 수 있는 최대 적재 작업 수입니다.">최대 병렬도<input type="number" min="1" max="32" value={form.max_parallelism} onChange={event => setForm({ ...form, max_parallelism: event.target.value })}/></label><label title="원천 DB 작업에 사용할 Airflow Pool 이름입니다.">원천 Pool<input value={form.source_pool} onChange={event => setForm({ ...form, source_pool: event.target.value })} placeholder="예: oracle_erp_pool"/></label><label title="적재 작업을 실행할 수 있는 시간 범위입니다.">허용 실행 시간대<input value={form.allowed_window} onChange={event => setForm({ ...form, allowed_window: event.target.value })} placeholder="예: 22:00~06:00"/></label></div><div className="modal-actions"><button type="button" className="ghost" onClick={() => setOpen(false)}>취소</button><button className="primary" disabled={busy}>{busy ? '생성 중…' : '계획·Chunk 생성'}</button></div></form></div>}{recommendProgress.open && <div className="modal-backdrop recommend-progress-backdrop" role="dialog" aria-modal="true"><section className="modal recommend-progress-modal"><div className="modal-head"><div><h2>{recommendProgress.recommendation ? 'AI 추천값 적용 확인' : recommendProgress.error ? 'AI 적재 설계 추천 오류' : 'AI 적재 설계 추천 처리 중'}</h2><p>{recommendProgress.recommendation ? '처리 결과를 확인한 후 추천값을 적용하세요.' : '선택된 메타 정보를 바탕으로 적재 설계를 계산하고 있습니다.'}</p></div><button type="button" className="ghost recommend-progress-close" aria-label="적재 설계 추천 팝업 닫기" onClick={() => setRecommendProgress(current => ({ ...current, open: false }))}><X size={18}/><span>닫기</span></button></div><div className="recommend-progress-body"><div className="recommend-progress-table"><b>대상 테이블</b><span>{form.identity ? form.identity.split('|').slice(-2).join('.') : '선택된 테이블'}</span></div>{['선택된 메타 테이블 확인','컬럼·PK·날짜 정보 조회','AI 또는 규칙 기반 추천 수행','분할·Chunk·병렬도 검증','추천 결과 생성'].map((label, index) => { const status = recommendProgress.stage < 0 ? (index === Math.max(0, recommendProgress.stage + 5) ? 'error' : index < 2 ? 'done' : 'pending') : index < recommendProgress.stage ? 'done' : index === recommendProgress.stage ? 'active' : 'pending'; return <div className={`recommend-progress-step ${status}`} key={label}><span className="recommend-progress-mark">{status === 'done' ? '✓' : status === 'error' ? '!' : index + 1}</span><div><b>{label}</b><small>{status === 'done' ? '완료' : status === 'active' ? '처리 중…' : status === 'error' ? '오류 발생' : '대기 중'}</small></div></div>})}{recommendProgress.recommendation && <div className="recommend-result"><b>추천 결과를 확인해 주세요</b><div><span>적재 방식</span><strong>{recommendProgress.recommendation.load_mode === 'INIT' ? '초기 적재' : '증분 적재'}</strong></div><div><span>분할 방식</span><strong>{strategies.find(item => item[0] === recommendProgress.recommendation.split_strategy)?.[1] || recommendProgress.recommendation.split_strategy}</strong></div><div><span>Chunk 목표</span><strong>{recommendProgress.recommendation.target_chunk_rows.toLocaleString()}건</strong></div><div><span>최대 병렬도</span><strong>{recommendProgress.recommendation.max_parallelism}</strong></div><p>{recommendProgress.recommendation.reason}</p><div className="recommend-result-actions"><button type="button" className="ghost" onClick={() => { setRecommendProgress({ open: false, stage: 0 }); toast('AI 추천을 확인했지만 적용하지 않았습니다.') }}>취소</button><button type="button" className="primary" onClick={() => { const recommendation = recommendProgress.recommendation; setForm((current: any) => ({ ...current, load_mode: recommendation.load_mode, split_strategy: recommendation.split_strategy, target_chunk_rows: recommendation.target_chunk_rows, max_parallelism: recommendation.max_parallelism })); setRecommendProgress({ open: false, stage: 0 }); toast('AI 추천값을 적용했습니다. 계획 저장 전에 값을 확인하세요.') }}>추천값 적용</button></div></div>}{recommendProgress.error && <><p className="recommend-progress-error">{recommendProgress.error}</p><div className="recommend-fallback-actions">{aiConfig.description_ai_provider !== 'manual' && <button type="button" className="ghost" onClick={() => void openManualRecommendation()} disabled={busy}>프롬프트 복사·응답 가져오기</button>}{aiConfig.description_ai_provider !== 'rules' && <button type="button" className="ghost" onClick={() => { setRecommendProgress({ open: false, stage: 0 }); void recommendPlan() }} disabled={busy}>규칙 기반으로 다시 추천</button>}</div></>}{recommendProgress.manualPrompt && !recommendProgress.recommendation && <div className="manual-load-ai-box"><b>프롬프트 복사·응답 가져오기</b><p>승인된 외부 AI에서 아래 프롬프트를 실행한 뒤 JSON 응답을 붙여넣어 주세요.</p><textarea readOnly value={recommendProgress.manualPrompt} aria-label="적재 추천 프롬프트"/><button type="button" className="ghost" onClick={() => void copyManualRecommendationPrompt()}>프롬프트 복사</button><label>AI 응답 JSON<textarea value={manualResponse} onChange={event => setManualResponse(event.target.value)} placeholder="외부 AI가 반환한 JSON을 붙여넣으세요." aria-label="적재 추천 AI 응답"/></label><div className="manual-load-ai-actions"><button type="button" className="ghost" onClick={() => setManualResponse('')}>응답 지우기</button><button type="button" className="primary" onClick={() => void validateManualRecommendation()} disabled={busy || !manualResponse.trim()}>응답 가져오기·검증</button></div></div>}</div>{recommendProgress.error && <div className="modal-actions"><button type="button" className="ghost" onClick={() => setRecommendProgress({ open: false, stage: 0 })}>닫기</button></div>}</section></div>}</>
}
