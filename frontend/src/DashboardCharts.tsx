import { useEffect, useId, useState } from 'react'
import { api } from './api'
import { chartDays, systemSlices, type AirflowHistory, type CollectionDay, type SystemCount } from './dashboardChartData'
import './dashboardCharts.css'

const palette = ['#4f46e5', '#0f9a89', '#e6802b', '#3a7bd5', '#a05bcc', '#94a3b8']
const number = new Intl.NumberFormat('ko-KR')
const statusLabel: Record<string, string> = { NOT_APPLICABLE: 'Airflow 미연동', FORBIDDEN: '적재 조회 권한 없음', UNAVAILABLE: 'Airflow 이력 조회 실패' }
type History = { trend: CollectionDay[]; metadata_systems?: SystemCount[]; airflow?: AirflowHistory }
type Breakdown = { source_id: number; source_name: string; table_count: number; view_count: number; captured_at: string }
const kstTime = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', timeStyle: 'short' })

export default function DashboardCharts({ canReadLoad, refreshKey }: { canReadLoad: boolean; refreshKey: string | null }) {
  const [data, setData] = useState<History | null>(null)
  const [failed, setFailed] = useState(false)
  const [source, setSource] = useState<'metadata' | 'airflow'>('metadata')
  const [selected, setSelected] = useState<number | null>(null)
  const [detailDate, setDetailDate] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ date: string; rows: Breakdown[] | null } | null>(null)
  const gradient = useId()
  useEffect(() => {
    if (!refreshKey) return
    const ctrl = new AbortController()
    setFailed(false)
    api<History>('/api/dashboard/collection-trend?days=30&include_operations=true', { signal: ctrl.signal })
      .then(value => { if (!ctrl.signal.aborted) setData(value) })
      .catch(() => { if (!ctrl.signal.aborted) setFailed(true) })
    return () => ctrl.abort()
  }, [refreshKey, canReadLoad])
  useEffect(() => {
    if (!detailDate) return
    const ctrl = new AbortController()
    api<{ breakdown: Breakdown[] }>(`/api/dashboard/collection-trend?days=30&selected_date=${encodeURIComponent(detailDate)}`, { signal: ctrl.signal })
      .then(value => { if (!ctrl.signal.aborted) setDetail({ date: detailDate, rows: value.breakdown }) })
      .catch(() => { if (!ctrl.signal.aborted) setDetail({ date: detailDate, rows: null }) })
    return () => ctrl.abort()
  }, [detailDate, refreshKey])
  const airflow = canReadLoad ? data?.airflow : undefined
  const mode = canReadLoad ? source : 'metadata'
  const days = chartDays(data?.trend ?? [], airflow)
  const day = days[selected ?? days.length - 1]
  const ticks = [0, 1, 2, 3, 4]
  const scale = (peak: number) => {
    const step = Math.max(1, peak / 4)
    const magnitude = 10 ** Math.floor(Math.log10(step))
    return ( [1, 2, 5, 10].find(n => n * magnitude >= step) ?? 10 ) * magnitude
  }
  const metaStep = scale(Math.max(0, ...days.map(d => d.metadata)))
  const airStep = scale(Math.max(0, ...days.map(d => d.airflow ?? 0)))
  const x = (i: number) => 54 + 606 * i / Math.max(1, days.length - 1)
  const y = (v: number, step: number) => 176 - 150 * v / (step * 4)
  const points = (key: 'metadata' | 'airflow', step: number) => days.map((d, i) => `${x(i)},${y(d[key] ?? 0, step)}`).join(' ')
  const meta = points('metadata', metaStep)
  const airAvailable = airflow?.status === 'AVAILABLE'
  const { total, slices } = systemSlices((mode === 'metadata' ? data?.metadata_systems : airflow?.systems) ?? [])
  let offset = 0
  const stops = slices.map(({ count }, i) => {
    const from = offset
    offset += count / total * 100
    return `${palette[i]} ${from}% ${i === slices.length - 1 ? 100 : offset}%`
  })
  const airMessage = statusLabel[airflow?.status ?? ''] ?? 'Airflow 데이터 미확인'
  return <div className="dashboard-charts-grid">
    <section className="panel dashboard-chart-card" aria-labelledby="ops-trend-title">
      <div className="dashboard-chart-head"><div><h2 id="ops-trend-title">최근 30일 운영 추이</h2><p>일별 메타 수집과 Airflow 적재 성공 이력 · 한국시간</p></div></div>
      <div className="dashboard-chart-legend"><span className="meta-chart-key">메타 수집 · 테이블 + 뷰 (좌)</span>{canReadLoad && <span className="air-chart-key">Airflow 적재 DAG 성공 (우)</span>}</div>
      {failed && <p className="dashboard-chart-notice" role="status">차트를 갱신하지 못했습니다.{data && ' 이전 조회 결과를 표시합니다.'}</p>}
      {!days.length ? <p className="dashboard-chart-empty">{failed ? '차트 데이터를 조회할 수 없습니다.' : '운영 추이를 불러오는 중입니다.'}</p> : <>
        <svg className="dashboard-series-svg" viewBox="0 0 716 205" role="img" aria-label="최근 30일 일별 메타 수집 객체와 Airflow 성공 실행 추이">
          <defs><linearGradient id={gradient} x2="0" y2="1"><stop stopColor="#4f46e5" stopOpacity=".19"/><stop offset="100%" stopColor="#4f46e5" stopOpacity=".01"/></linearGradient></defs>
          {ticks.map(t => <g key={t}><line x1="54" x2="660" y1={y(t, 1)} y2={y(t, 1)} stroke="#e8edf5" strokeDasharray={t ? '4 4' : undefined}/><text x="46" y={y(t, 1) + 4} textAnchor="end" fill="#4f46e5">{number.format(t * metaStep)}</text>{airAvailable && <text x="668" y={y(t, 1) + 4} fill="#087f70">{number.format(t * airStep)}</text>}</g>)}
          <polygon points={`54,176 ${meta} 660,176`} fill={`url(#${gradient})`}/>
          <polyline points={meta} className="dashboard-series-meta"/>
          {airAvailable && <polyline points={points('airflow', airStep)} className="dashboard-series-air"/>}
          {days.map((d, i) => {
            const active = i === (selected ?? days.length - 1)
            return <g key={d.date} onPointerEnter={() => setSelected(i)}>
              {active && <><line x1={x(i)} x2={x(i)} y1="26" y2="176" stroke="#a0aec0" strokeDasharray="3 3"/><circle cx={x(i)} cy={y(d.metadata, metaStep)} r="4" fill="#4f46e5"/><circle cx={x(i)} cy={y(d.airflow ?? 0, airStep)} r="3" fill="#0f9a89" visibility={airAvailable ? 'visible' : 'hidden'}/></>}
              {(i % 7 === 0 || i === days.length - 1) && i !== days.length - 2 && <text x={x(i)} y="195" textAnchor="middle" fill="#64748b">{d.date.slice(5).replace('-', '/')}</text>}
              <rect x={x(i) - 10} y="20" width="20" height="158" fill="transparent"><title>{d.date} · 메타 {d.metadata}개{d.airflow != null ? ` · 적재 ${d.airflow}건` : ''}</title></rect>
            </g>
          })}
        </svg>
        <div className="dashboard-day-detail"><label>일자 <select value={day?.date ?? ''} onChange={event => setSelected(days.findIndex(d => d.date === event.target.value))}>{days.map(d => <option key={d.date}>{d.date}</option>)}</select></label><span>메타 <strong>{number.format(day?.metadata ?? 0)}개</strong></span>{canReadLoad && <span>{airAvailable ? <>적재 <strong>{number.format(day?.airflow ?? 0)}건</strong></> : airMessage}</span>}</div>
        {day && <div><button type="button" className="ghost" aria-expanded={detailDate !== null} onClick={() => { setDetail(null); setDetailDate(detailDate === day.date ? null : day.date) }}>{detailDate === day.date ? 'DB별 상세 닫기' : `${day.date} DB별 상세`}</button></div>}
        {detailDate && <div className="dashboard-chart-breakdown"><strong>{detailDate} 수집 상세</strong>
          {detail?.date !== detailDate ? <p role="status">불러오는 중입니다.</p> : detail.rows == null ? <p role="status">DB별 상세를 조회하지 못했습니다.</p> : !detail.rows.length ? <p>해당 일자의 수집 이력이 없습니다.</p> : <table><thead><tr><th scope="col">DB 연결</th><th scope="col">테이블</th><th scope="col">뷰</th><th scope="col">수집 시각</th></tr></thead><tbody>{detail.rows.map(row => <tr key={row.source_id}><th scope="row">{row.source_name}</th><td>{number.format(row.table_count)}</td><td>{number.format(row.view_count)}</td><td>{kstTime.format(new Date(row.captured_at))}</td></tr>)}</tbody></table>}
        </div>}
      </>}
    </section>
    <section className="panel dashboard-chart-card dashboard-share-card" aria-labelledby="ops-share-title">
      <div className="dashboard-chart-head"><div><h2 id="ops-share-title">시스템별 비율</h2><p>같은 30일 기간의 누적 비중</p></div><select aria-label="시스템 비율 지표" value={mode} onChange={event => setSource(event.target.value === 'airflow' ? 'airflow' : 'metadata')}><option value="metadata">메타 수집</option><option value="airflow" disabled={!canReadLoad}>Airflow 적재</option></select></div>
      {total > 0 ? <>
        <div className="dashboard-share-donut" aria-hidden="true" style={{ background: `conic-gradient(${stops.join(',')})` }}><div><b>{number.format(total)}</b><small>{mode === 'metadata' ? '수집 객체' : '성공 실행'}</small></div></div>
        <ul className="dashboard-share-legend">{slices.map(({ name, count }, i) => <li key={`${name}-${i}`}><i style={{ backgroundColor: palette[i] }} aria-hidden="true"/><span title={name}>{name}</span><small>{number.format(count)}{mode === 'metadata' ? '개' : '건'}</small><strong>{(count / total * 100).toFixed(1)}%</strong></li>)}</ul>
      </> : <p className="dashboard-chart-empty">{data ? mode === 'airflow' && !airAvailable ? airMessage : '해당 기간에 집계된 데이터가 없습니다.' : failed ? '비율 데이터를 조회할 수 없습니다.' : '시스템 비율을 불러오는 중입니다.'}</p>}
      <p className="dashboard-share-basis">{mode === 'metadata' ? '수집 시스템(DB 연결)별 일일 최신 스냅샷의 테이블·뷰 합계' : '적재 실행기가 설정된 DAG의 성공 실행 수 · 적재 행 수 아님'}</p>
    </section>
  </div>
}
