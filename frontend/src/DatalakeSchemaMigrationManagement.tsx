import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, CircleAlert, Database, RefreshCw, Search, X } from 'lucide-react'
import { api } from './api'
import DatalakeMigrationPlanPanel from './DatalakeMigrationPlanPanel'
import {
  buildMigrationManagementRows,
  getMigrationStatusTargets,
  migrationIdentityKey,
} from './datalakeMigrationManagement.js'
import './datalake-migration-management.css'

type Props = {
  initialTable?: any
  onBack: () => void
  toast: (message: string) => void
}

type Filter = 'ALL' | 'NEEDS_MIGRATION' | 'CURRENT' | 'BLOCKED' | 'CREATE_REQUIRED'

const physicalIdentityKey = (table: any) => [table.system_cd, table.instance_name, table.postfix || '', table.owner, table.table_name].join('|')
const identities = (tables: any[]) => tables.map(table => ({
  system_cd: table.system_cd,
  instance_name: table.instance_name,
  postfix: table.postfix || '',
  owner: table.owner,
  table_name: table.table_name,
}))

const labels: Record<string, string> = {
  NEEDS_MIGRATION: '구조 변경 필요',
  CURRENT: '현재 구조 일치',
  CREATE_REQUIRED: 'ST/L0 생성 필요',
  CHECK_FAILED: '상태 확인 실패',
  UNAVAILABLE: 'Target 확인 불가',
  CHECK_PENDING: '확인 대기',
}

const statusClass: Record<string, string> = {
  NEEDS_MIGRATION: 'warning',
  CURRENT: 'success',
  CREATE_REQUIRED: 'muted',
  CHECK_FAILED: 'danger',
  UNAVAILABLE: 'danger',
  CHECK_PENDING: 'muted',
}

async function mapConcurrent<T, R>(items: T[], concurrency: number, worker: (item: T) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length)
  let nextIndex = 0
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex++
      results[index] = await worker(items[index])
    }
  }))
  return results
}

const askForMigrationApply = (message: string) => new Promise<boolean>(resolve => {
  window.dispatchEvent(new CustomEvent('metavault:confirm', {
    detail: { title: '구조 변경 적용 확인', message, confirmLabel: '빈 테이블 구조 적용', danger: true, resolve },
  }))
})

export default function DatalakeSchemaMigrationManagement({ initialTable, onBack, toast }: Props) {
  const [tables, setTables] = useState<any[]>([])
  const [physicalStatuses, setPhysicalStatuses] = useState<Record<string, any>>({})
  const [migrationStatuses, setMigrationStatuses] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<Filter>('ALL')
  const [query, setQuery] = useState('')
  const [focusedKey, setFocusedKey] = useState('')
  const [activeTable, setActiveTable] = useState<any>(null)
  const [plan, setPlan] = useState<any>(null)
  const [planOpen, setPlanOpen] = useState(false)
  const [planBusy, setPlanBusy] = useState(false)
  const requestId = useRef(0)

  useEffect(() => {
    if (initialTable) setFocusedKey(migrationIdentityKey(initialTable))
  }, [initialTable])

  const refresh = useCallback(async () => {
    const requestIdForLoad = ++requestId.current
    setLoading(true)
    setError('')
    try {
      const allTables: any[] = []
      let pages = 1
      for (let page = 1; page <= pages && page <= 100; page += 1) {
        const response = await api<any>(`/api/metadata/registered?page=${page}&page_size=200`)
        allTables.push(...(response.items || []))
        pages = Math.max(1, Number(response.pages || 1))
      }
      const physicalResponse = allTables.length
        ? await api<any>('/api/metadata/registered/datalake-status', { method: 'POST', body: JSON.stringify(identities(allTables)) })
        : { items: [] }
      const byPhysicalKey = new Map(allTables.map(table => [physicalIdentityKey(table), table]))
      const physical: Record<string, any> = {}
      for (const item of physicalResponse.items || []) {
        const table = byPhysicalKey.get(item.key)
        if (table) physical[migrationIdentityKey(table)] = item
      }
      const targets = getMigrationStatusTargets(allTables, physical)
      const results = await mapConcurrent(targets, 4, async table => {
        try {
          const status = await api<any>('/api/metadata/registered/datalake-migrations/status', {
            method: 'POST',
            body: JSON.stringify(identities([table])[0]),
          })
          return [migrationIdentityKey(table), status] as const
        } catch (statusError) {
          return [migrationIdentityKey(table), { status: 'UNKNOWN', reason: (statusError as Error).message }] as const
        }
      })
      if (requestId.current !== requestIdForLoad) return
      setTables(allTables)
      setPhysicalStatuses(physical)
      setMigrationStatuses(Object.fromEntries(results))
    } catch (loadError) {
      if (requestId.current !== requestIdForLoad) return
      setError((loadError as Error).message || '구조 변경 상태를 불러오지 못했습니다.')
      setTables([])
      setPhysicalStatuses({})
      setMigrationStatuses({})
    } finally {
      if (requestId.current === requestIdForLoad) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => { requestId.current += 1 }
  }, [refresh])

  useEffect(() => {
    if (!planOpen) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !planBusy) setPlanOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [planOpen, planBusy])

  const rows = useMemo(() => buildMigrationManagementRows(tables, physicalStatuses, migrationStatuses), [tables, physicalStatuses, migrationStatuses])
  const counts = useMemo(() => rows.reduce<Record<string, number>>((result, row) => {
    result[row.state] = (result[row.state] || 0) + 1
    return result
  }, {}), [rows])
  const visibleRows = useMemo(() => rows.filter(row => {
    const matchesFilter = filter === 'ALL' || (filter === 'BLOCKED'
      ? ['CHECK_FAILED', 'UNAVAILABLE'].includes(row.state)
      : row.state === filter)
    const haystack = `${row.table.system_cd} ${row.table.instance_name} ${row.table.owner} ${row.table.table_name}`.toLowerCase()
    return matchesFilter && (!query.trim() || haystack.includes(query.trim().toLowerCase()))
  }), [rows, filter, query])

  const openPlan = async (table: any) => {
    setActiveTable(table)
    setPlan(null)
    setPlanOpen(true)
    setPlanBusy(true)
    try {
      const result = await api<any>('/api/metadata/registered/datalake-migrations/preview', {
        method: 'POST',
        body: JSON.stringify(identities([table])[0]),
      })
      setPlan(result)
    } catch (previewError) {
      setPlanOpen(false)
      toast((previewError as Error).message || '구조 변경 계획을 확인하지 못했습니다.')
    } finally {
      setPlanBusy(false)
    }
  }

  const applyPlan = async () => {
    if (!plan?.plan_id || plan.route !== 'APPLY_EMPTY' || plan.status !== 'READY') return
    const accepted = await askForMigrationApply(`${activeTable?.owner}.${activeTable?.table_name}의 ST/L0 구조를 변경합니다. 두 테이블이 비어 있는지 적용 직전에 다시 확인합니다. 계속하시겠습니까?`)
    if (!accepted) return
    setPlanBusy(true)
    try {
      await api('/api/metadata/registered/datalake-migrations/apply-empty?confirm=true', {
        method: 'POST',
        body: JSON.stringify({ plan_id: plan.plan_id }),
      })
      setPlanOpen(false)
      toast('비어 있는 ST/L0 테이블에 구조를 적용했습니다.')
      await refresh()
    } catch (applyError) {
      toast((applyError as Error).message || '구조 변경 적용에 실패했습니다.')
    } finally {
      setPlanBusy(false)
    }
  }

  const setQuickFilter = (next: Filter) => setFilter(next)

  return <div className="datalake-migration-management">
    <header className="dmm-header">
      <div>
        <button type="button" className="ghost dmm-back" onClick={onBack}><ArrowLeft size={16}/>적재 운영으로 돌아가기</button>
        <h2>테이블 구조 변경 관리</h2>
        <p>등록된 테이블의 실제 ST/L0 구조를 확인하고, 안전 조건을 충족하는 변경 계획만 검토·적용합니다.</p>
      </div>
      <button type="button" className="ghost dmm-refresh" onClick={() => void refresh()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''}/>{loading ? '상태 확인 중…' : '상태 새로고침'}</button>
    </header>

    <section className="dmm-summary" aria-label="구조 변경 상태 요약">
      <button type="button" className={filter === 'ALL' ? 'selected' : ''} onClick={() => setQuickFilter('ALL')}><span>전체</span><b>{rows.length}</b></button>
      <button type="button" className={`warning ${filter === 'NEEDS_MIGRATION' ? 'selected' : ''}`} onClick={() => setQuickFilter('NEEDS_MIGRATION')}><span>구조 변경 필요</span><b>{counts.NEEDS_MIGRATION || 0}</b></button>
      <button type="button" className={`success ${filter === 'CURRENT' ? 'selected' : ''}`} onClick={() => setQuickFilter('CURRENT')}><span>현재 구조 일치</span><b>{counts.CURRENT || 0}</b></button>
      <button type="button" className={`danger ${filter === 'BLOCKED' ? 'selected' : ''}`} onClick={() => setQuickFilter('BLOCKED')}><span>확인 필요</span><b>{(counts.CHECK_FAILED || 0) + (counts.UNAVAILABLE || 0)}</b></button>
    </section>

    <section className="panel dmm-list-panel">
      <div className="dmm-list-toolbar">
        <div><h3><Database size={17}/>등록 테이블 현황</h3><span>{loading ? '실제 구조 비교 중' : `${visibleRows.length}개 표시`}</span></div>
        <label className="dmm-search"><Search size={16}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="시스템·소스·Owner·테이블 검색" aria-label="테이블 검색"/><button type="button" className="ghost" onClick={() => setQuery('')} aria-label="검색어 지우기"><X size={14}/></button></label>
      </div>
      {error && <div className="dmm-error"><CircleAlert size={17}/><span>{error}</span><button type="button" className="ghost" onClick={() => void refresh()}>다시 시도</button></div>}
      {loading && !rows.length && <div className="dmm-empty"><RefreshCw size={18} className="spin"/>실제 Datalake 구조를 확인하고 있습니다.</div>}
      {!loading && !error && !visibleRows.length && <div className="dmm-empty">조건에 맞는 테이블이 없습니다. 검색어 또는 상태 필터를 바꿔 보세요.</div>}
      <div className="dmm-table-list">
        {visibleRows.map(row => {
          const label = labels[row.state] || '확인 대기'
          const migration = row.migration
          const physical = row.physical
          const isFocused = row.key === focusedKey
          return <article className={`dmm-row ${isFocused ? 'focused' : ''}`} key={row.key}>
            <div className="dmm-row-main">
              <div className="dmm-row-title"><div><strong>{row.table.owner}.{row.table.table_name}</strong><small>{row.table.system_cd} · {row.table.instance_name}{row.table.postfix ? ` · ${row.table.postfix}` : ''}</small></div><span className={`dmm-status ${statusClass[row.state] || 'muted'}`}>{label}</span></div>
              <div className="dmm-row-meta"><span>ST {physical?.st_table_exists === true ? '있음' : physical?.st_table_exists === false ? '없음' : '확인 불가'}</span><span>L0 {physical?.table_exists === true ? '있음' : physical?.table_exists === false ? '없음' : '확인 불가'}</span>{migration?.route && <span>{migration.route === 'APPLY_EMPTY' ? '빈 테이블 적용 가능' : migration.route === 'TOBE_REQUIRED' ? 'TO-BE 검토 필요' : migration.route === 'NO_CHANGE' ? '변경 없음' : migration.route}</span>}</div>
              {(migration?.reason || physical?.message) && <p className="dmm-row-reason">{migration?.reason || physical?.message}</p>}
            </div>
            <div className="dmm-row-actions">{row.state === 'NEEDS_MIGRATION' ? <button type="button" className="primary" onClick={() => void openPlan(row.table)}>계획 확인</button> : <button type="button" className="ghost" disabled title={migration?.reason || physical?.message || '구조 변경 계획 확인 대상이 아닙니다.'}>계획 확인</button>}</div>
          </article>
        })}
      </div>
    </section>

    {planOpen && <div className="dmm-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !planBusy) setPlanOpen(false) }}>
      <section className="dmm-modal" role="dialog" aria-modal="true" aria-labelledby="dmm-plan-title">
        <header><div><h3 id="dmm-plan-title">ST/L0 구조 변경 계획</h3><p>{activeTable?.owner}.{activeTable?.table_name} · 변경 내역과 안전 조건을 확인하세요.</p></div><button type="button" className="ghost" aria-label="계획 닫기" onClick={() => setPlanOpen(false)} disabled={planBusy}><X size={18}/></button></header>
        {planBusy && !plan ? <div className="dmm-empty"><RefreshCw size={18} className="spin"/>변경 계획을 다시 확인하고 있습니다.</div> : plan && <DatalakeMigrationPlanPanel plan={plan} busy={planBusy} onApply={() => void applyPlan()}/>}
        <footer><button type="button" className="ghost" onClick={() => setPlanOpen(false)} disabled={planBusy}>닫기</button></footer>
      </section>
    </div>}
  </div>
}
