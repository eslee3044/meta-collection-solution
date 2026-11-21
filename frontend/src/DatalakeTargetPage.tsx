import { FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, Database, LockKeyhole, RefreshCw, RotateCcw, ShieldCheck } from 'lucide-react'
import { api } from './api'
import './datalake-target.css'

type TargetType = 'bigquery' | 'postgresql' | 'redshift'
type SqlMode = 'disable' | 'prefer' | 'require'
type TargetStatus = {
  configured: boolean
  target_type: TargetType | null
  status: string
  credential_configured: boolean
  connection_summary: Record<string, string | number | null>
  dedicated_encryption_key: boolean
  last_tested_at: string | null
  created_at: string | null
  updated_at: string | null
}
type TargetForm = {
  target_type: TargetType
  host: string
  port: number
  database: string
  username: string
  password: string
  ssl_mode: SqlMode
  connect_timeout: number
  project_id: string
  dataset: string
  location: string
  service_account_json: string
}

const labels: Record<TargetType, string> = { bigquery: 'BigQuery', postgresql: 'PostgreSQL', redshift: 'Redshift' }
const emptyForm = (target_type: TargetType = 'bigquery'): TargetForm => ({
  target_type,
  host: '',
  port: target_type === 'redshift' ? 5439 : 5432,
  database: '',
  username: '',
  password: '',
  ssl_mode: target_type === 'redshift' ? 'require' : 'prefer',
  connect_timeout: 5,
  project_id: '',
  dataset: '',
  location: '',
  service_account_json: '',
})
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('ko-KR') : '아직 확인하지 않음'

function formFromStatus(status: TargetStatus): TargetForm {
  const type = status.target_type || 'bigquery'
  const summary = status.connection_summary || {}
  return {
    ...emptyForm(type),
    host: String(summary.host || ''),
    port: Number(summary.port || (type === 'redshift' ? 5439 : 5432)),
    database: String(summary.database || ''),
    username: String(summary.username || ''),
    ssl_mode: (summary.ssl_mode as SqlMode) || (type === 'redshift' ? 'require' : 'prefer'),
    project_id: String(summary.project_id || ''),
    dataset: String(summary.dataset || ''),
    location: String(summary.location || ''),
  }
}

function requestPayload(form: TargetForm) {
  if (form.target_type === 'bigquery') return {
    target_type: form.target_type,
    project_id: form.project_id.trim(),
    dataset: form.dataset.trim(),
    location: form.location.trim() || null,
    service_account_json: form.service_account_json,
    connect_timeout: form.connect_timeout,
  }
  return {
    target_type: form.target_type,
    host: form.host.trim(),
    port: form.port,
    database: form.database.trim(),
    username: form.username.trim(),
    password: form.password,
    ssl_mode: form.ssl_mode,
    connect_timeout: form.connect_timeout,
  }
}

export default function DatalakeTargetPage({ isAdmin, toast }: { isAdmin: boolean; toast: (message: string) => void }) {
  const [status, setStatus] = useState<TargetStatus | null>(null)
  const [form, setForm] = useState<TargetForm>(() => emptyForm())
  const [replacing, setReplacing] = useState(false)
  const [tested, setTested] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [testMessage, setTestMessage] = useState('')

  const load = async () => {
    const result = await api<TargetStatus>('/api/admin/datalake-target')
    setStatus(result)
    if (!result.configured) setForm(emptyForm('bigquery'))
    return result
  }
  useEffect(() => { if (isAdmin) void load().catch(error => setError((error as Error).message)) }, [isAdmin])

  const set = <K extends keyof TargetForm>(key: K, value: TargetForm[K]) => {
    setForm(current => ({ ...current, [key]: value }))
    setTested(false); setTestMessage('')
  }
  const changeType = (type: TargetType) => {
    setForm(emptyForm(type)); setTested(false); setTestMessage(''); setError('')
  }
  const testConnection = async () => {
    setTesting(true); setError(''); setTestMessage('')
    try {
      const result = await api<any>('/api/admin/datalake-target/test', { method: 'POST', body: JSON.stringify(requestPayload(form)) })
      setTested(true)
      setTestMessage(form.target_type === 'bigquery'
        ? 'BigQuery Dataset 조회와 쿼리 권한을 확인했습니다. 아직 저장되지는 않았습니다.'
        : `${labels[form.target_type]} ${result.server_version || ''} 연결과 임시 테이블 쓰기·삭제 권한을 확인했습니다. 아직 저장되지는 않았습니다.`)
    } catch (error) { setTested(false); setError((error as Error).message) }
    finally { setTesting(false) }
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!tested) { setError('현재 입력값으로 연결 테스트를 먼저 완료하세요.'); return }
    setSaving(true); setError('')
    try {
      const path = replacing ? '/api/admin/datalake-target/replace' : '/api/admin/datalake-target'
      const base = requestPayload(form)
      await api<TargetStatus>(path, { method: 'POST', body: JSON.stringify(replacing ? { ...base, confirm_replace: true } : base) })
      const wasReplacing = replacing
      await load(); setReplacing(false); setTested(false); setTestMessage('')
      toast(wasReplacing ? 'Datalake 대상 DB와 접속정보를 안전하게 교체했습니다.' : 'Datalake 대상 DB를 암호화하여 저장했습니다.')
    } catch (error) { setError((error as Error).message) }
    finally { setSaving(false) }
  }
  const retest = async () => {
    setTesting(true); setError('')
    try {
      const testedType = status?.target_type
      await api<any>('/api/admin/datalake-target/retest', { method: 'POST' }); await load()
      toast(`저장된 ${testedType ? labels[testedType] : 'Datalake'} 접속정보로 연결을 확인했습니다.`)
    } catch (error) { setError((error as Error).message); await load().catch(() => undefined) }
    finally { setTesting(false) }
  }

  if (!isAdmin) return <div className="alert"><CircleAlert size={16}/>시스템 관리 권한이 필요합니다.</div>
  if (!status) return <div className="loading"><RefreshCw className="spin"/>Datalake 대상 설정을 불러오는 중...</div>

  const showForm = !status.configured || replacing
  const currentLabel = status.target_type ? labels[status.target_type] : '설정 후 결정'
  const summary = status.connection_summary || {}
  return <>
    <div className="admin-settings-section-heading datalake-settings-heading"><div><h2>Datalake 대상 DB</h2><p>대상 DB 종류를 선택하고 해당 DB의 접속정보를 안전하게 설정합니다.</p></div></div>
    <div className="datalake-target-layout admin-settings-datalake-content">
      <section className="panel datalake-target-card datalake-linked-database datalake-target-overview">
        <div className="panel-head"><div><h3>Datalake 대상 및 메타 등록 기본 DB</h3><p>선택한 DB를 실제 적재 대상과 TB_META_TABLES_EXT.TGT_DATABASE_NAME에 동일하게 사용합니다.</p></div><Database size={20}/></div>
        <div className="datalake-linked-database-value">
          <div className="datalake-target-icon"><Database size={20}/></div>
          <div><span>현재 대상</span><b>{status.configured ? `${currentLabel} Datalake` : '설정되지 않음'}</b><small>{status.configured ? '접속정보 원문은 암호화 저장되며 메타 등록 기본 대상과 함께 관리됩니다.' : 'DB 종류를 선택하고 연결 테스트를 완료하세요.'}</small></div>
          <div className="datalake-overview-badges"><span className={`datalake-link-badge ${status.configured ? 'linked' : ''}`}>{status.configured ? '메타 연동' : '연동 대기'}</span><span className={`datalake-target-status ${status.status}`}>{status.status === 'connected' ? '연결 정상' : status.status === 'failed' ? '연결 실패' : '미설정'}</span></div>
        </div>
      </section>

      {status.configured && !replacing && <section className="panel datalake-target-card">
        <div className="panel-head"><div><h3>저장된 접속정보</h3><p>식별에 필요한 비민감 항목만 표시하며 인증정보 원문은 반환하지 않습니다.</p></div><LockKeyhole size={20}/></div>
        <div className="datalake-target-facts">
          <div><span>대상 종류</span><b>{currentLabel}</b></div>
          {status.target_type === 'bigquery' ? <><div><span>Project ID</span><b>{summary.project_id || '—'}</b></div><div><span>Dataset</span><b>{summary.dataset || '—'}</b></div><div><span>Location</span><b>{summary.location || '자동'}</b></div></> : <><div><span>Host / Port</span><b>{summary.host || '—'}:{summary.port || '—'}</b></div><div><span>Database</span><b>{summary.database || '—'}</b></div><div><span>사용자명</span><b>{summary.username || '—'}</b></div></>}
          <div><span>인증정보</span><b>{status.credential_configured ? '암호화 설정됨' : '미설정'}</b></div><div><span>최근 연결 테스트</span><b>{formatDate(status.last_tested_at)}</b></div><div><span>전용 암호화 키</span><b>{status.dedicated_encryption_key ? '설정됨' : '시스템 키 사용 중'}</b></div>
        </div>
        {!status.dedicated_encryption_key && <div className="datalake-key-warning"><CircleAlert size={17}/><div><b>전용 인증정보 암호화 키를 권장합니다.</b><p>운영 환경에는 METAVAULT_CREDENTIAL_ENCRYPTION_KEY를 별도로 설정하세요.</p></div></div>}
        <div className="datalake-target-actions"><button className="ghost" disabled={testing} onClick={retest}>{testing && <RefreshCw className="spin" size={16}/>}저장된 정보로 연결 확인</button><button className="primary" onClick={() => { setReplacing(true); setForm(formFromStatus(status)); setError(''); setTestMessage('') }}><RotateCcw size={16}/>대상 DB / 접속정보 교체</button></div>
      </section>}

      {showForm && <form className="panel datalake-target-form" onSubmit={submit}>
        <div className="panel-head"><div><h3>{replacing ? '대상 DB와 접속정보 교체' : '대상 데이터베이스 설정'}</h3><p>{replacing ? '새 정보의 연결 테스트가 실패하면 기존 설정은 그대로 유지됩니다.' : '선택한 데이터베이스에 맞는 접속정보를 입력하세요.'}</p></div><ShieldCheck size={20}/></div>
        <div className="datalake-type-selector" role="radiogroup" aria-label="Datalake 대상 데이터베이스">{(['bigquery','postgresql','redshift'] as TargetType[]).map(type => <button key={type} type="button" role="radio" aria-checked={form.target_type === type} className={form.target_type === type ? 'selected' : ''} onClick={() => changeType(type)}><Database size={17}/><span>{labels[type]}</span><small>{type === 'bigquery' ? 'Google Cloud' : type === 'redshift' ? 'Amazon Web Services' : 'PostgreSQL'}</small></button>)}</div>
        <div className="form-grid datalake-form-grid">
          {form.target_type === 'bigquery' ? <>
            <label>Project ID<input required autoComplete="off" value={form.project_id} onChange={event => set('project_id', event.target.value)} placeholder="예: my-analytics-project"/></label>
            <label>Dataset<input required autoComplete="off" value={form.dataset} onChange={event => set('dataset', event.target.value)} placeholder="예: metadata_lake"/></label>
            <label>Location<input autoComplete="off" value={form.location} onChange={event => set('location', event.target.value)} placeholder="예: asia-northeast3 (선택)"/></label>
            <label>연결 제한 시간(초)<input required type="number" min={1} max={30} value={form.connect_timeout} onChange={event => set('connect_timeout', Number(event.target.value))}/></label>
            <label className="span-2">서비스 계정 JSON<textarea required rows={8} autoComplete="off" value={form.service_account_json} onChange={event => set('service_account_json', event.target.value)} placeholder='{"type":"service_account","project_id":"..."}'/><small>JSON 원문은 암호화 저장되며 응답·로그·화면에 다시 표시하지 않습니다.</small></label>
          </> : <>
            <label>호스트<input required autoComplete="off" value={form.host} onChange={event => set('host', event.target.value)} placeholder={form.target_type === 'redshift' ? 'cluster.region.redshift.amazonaws.com' : '예: datalake-postgres'}/></label>
            <label>포트<input required type="number" min={1} max={65535} value={form.port} onChange={event => set('port', Number(event.target.value))}/></label>
            <label>데이터베이스<input required autoComplete="off" value={form.database} onChange={event => set('database', event.target.value)}/></label>
            <label>사용자명<input required autoComplete="off" value={form.username} onChange={event => set('username', event.target.value)}/></label>
            <label>SSL 모드<select value={form.ssl_mode} onChange={event => set('ssl_mode', event.target.value as SqlMode)}><option value="prefer">prefer (가능하면 TLS)</option><option value="require">require (TLS 필수)</option><option value="disable">disable (로컬 테스트 전용)</option></select></label>
            <label>연결 제한 시간(초)<input required type="number" min={1} max={30} value={form.connect_timeout} onChange={event => set('connect_timeout', Number(event.target.value))}/></label>
            <label className="span-2">비밀번호<input required type="password" autoComplete="new-password" value={form.password} onChange={event => set('password', event.target.value)}/><small>비밀번호는 암호화 저장되며 응답·로그·화면에 다시 표시하지 않습니다.</small></label>
          </>}
        </div>
        {error && <div className="alert"><CircleAlert size={16}/>{error}</div>}{testMessage && <div className="test-success"><CheckCircle2 size={16}/>{testMessage}</div>}
        <div className="datalake-target-actions">{replacing && <button type="button" className="ghost" onClick={() => { setReplacing(false); setTested(false); setError(''); setTestMessage('') }}>취소</button>}<button type="button" className="ghost" disabled={testing || saving} onClick={testConnection}>{testing && <RefreshCw className="spin" size={16}/>}연결 및 권한 테스트</button><button className="primary" disabled={!tested || testing || saving}>{saving && <RefreshCw className="spin" size={16}/>}테스트 완료 정보 저장</button></div>
      </form>}
    </div>
  </>
}
