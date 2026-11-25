import type { ReactNode } from 'react'

type Props = {
  plan: any
  busy: boolean
  onApply: () => void
}

export default function DatalakeMigrationPlanPanel({ plan, busy, onApply }: Props): ReactNode {
  if (!plan) return null
  const canApply = plan.route === 'APPLY_EMPTY' && plan.status === 'READY'
  const compareSummary = (item: any) => {
    const comparison = item.comparison || {}
    const pieces = [
      (comparison.added || []).length ? `추가 ${comparison.added.map((column: any) => column.name).join(', ')}` : '',
      (comparison.removed || []).length ? `삭제 ${comparison.removed.map((column: any) => column.name).join(', ')}` : '',
      (comparison.changed_columns || []).length ? `변경 ${comparison.changed_columns.map((column: any) => column.name).join(', ')}` : '',
      comparison.order_changed ? '컬럼 순서 변경' : '',
    ].filter(Boolean)
    return pieces.length ? pieces.join(' · ') : '목표 구조와 같습니다.'
  }

  return <section className={`datalake-migration-plan ${canApply ? 'ready' : 'blocked'}`} aria-live="polite">
    <header><div><b>계획 #{plan.plan_id}</b><span className={`migration-route route-${String(plan.route || '').toLowerCase()}`}>{plan.route === 'APPLY_EMPTY' ? '빈 테이블 직접 변경' : plan.route === 'TOBE_REQUIRED' ? 'TO-BE 전환 필요' : plan.route === 'NO_CHANGE' ? '변경 없음' : plan.route === 'CREATE_NEW' ? '신규 생성 경로' : '차단'}</span></div></header>
    <p>{plan.reason}</p>
    {(plan.physical?.objects || []).map((item: any) => {
      const comparison = (plan.comparisons || []).find((candidate: any) => candidate.schema === item.schema && candidate.table === item.table)
      return <div className="migration-object" key={`${item.schema}.${item.table}`}><b>{item.schema}.{item.table}</b><span>{item.exists ? item.has_rows === false ? '행 없음 확인' : item.has_rows === true ? '데이터 있음' : '행 상태 확인 불가' : '테이블 없음'}</span><small>{comparison ? compareSummary(comparison) : '현재 구조 비교 대상이 아닙니다.'}</small></div>
    })}
    {!!(plan.blocking_reasons || []).length && <ul className="migration-blockers">{plan.blocking_reasons.map((reason: string, index: number) => <li key={`${index}-${reason}`}>{reason}</li>)}</ul>}
    {plan.route === 'TOBE_REQUIRED' && <p className="migration-note">데이터가 있는 테이블입니다. 운영 교체용 TO-BE 생성·검증·승인 단계는 아직 제공되지 않아 물리 변경을 차단했습니다.</p>}
    <footer>{canApply ? <button type="button" className="danger-button" disabled={busy} onClick={onApply}>{busy ? '구조 재검증·적용 중…' : '비어 있는 ST/L0에 구조 적용'}</button> : <span>이 계획에서는 물리 구조를 변경할 수 없습니다.</span>}</footer>
  </section>
}
