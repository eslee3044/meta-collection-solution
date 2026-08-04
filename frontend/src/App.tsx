import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react'
import {
  Activity, CalendarClock, Check, ChevronDown, CircleAlert, Database, Eye, Gauge,
  KeyRound, LayoutDashboard, LockKeyhole, LogOut, Menu as MenuIcon, Play, Plus,
  RefreshCw, Search, Server, ShieldCheck, TableProperties, Trash2, Pencil, Download, Upload, BookOpen, Users, X, Zap,
} from 'lucide-react'
import { api, ApiError, fmt } from './api'
import type { Capabilities, Job, Menu, Permission, Role, Run, Source, User } from './types'

type Page = 'dashboard' | 'sources' | 'metadata' | 'jobs' | 'users' | 'roles'
const nav: { id: Page; label: string; icon: typeof Gauge; group: string }[] = [
  { id: 'dashboard', label: '대시보드', icon: LayoutDashboard, group: 'OVERVIEW' },
  { id: 'sources', label: 'DB 접속 관리', icon: Database, group: 'DATA MANAGEMENT' },
  { id: 'metadata', label: '스키마 정보', icon: TableProperties, group: 'DATA MANAGEMENT' },
  { id: 'jobs', label: '수집 스케줄', icon: CalendarClock, group: 'AUTOMATION' },
  { id: 'users', label: '사용자 관리', icon: Users, group: 'ADMINISTRATION' },
  { id: 'roles', label: '역할 및 권한', icon: ShieldCheck, group: 'ADMINISTRATION' },
]

const dbNames: Record<string, string> = { postgresql: 'PostgreSQL', mysql: 'MySQL', mariadb: 'MariaDB', mssql: 'SQL Server', oracle: 'Oracle', sqlite: 'SQLite' }
const dbPorts: Record<string, number> = { postgresql: 5432, mysql: 3306, mariadb: 3306, mssql: 1433, oracle: 1521 }
const fmtBytes = (value?: number | null) => {
  if (value == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = Math.abs(value), unit = 0
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++ }
  return `${value < 0 ? '-' : ''}${size.toFixed(unit ? 1 : 0)} ${units[unit]}`
}

function useLoad<T>(path: string, fallback: T, deps: unknown[] = []) {
  const [data, setData] = useState<T>(fallback)
  const [loading, setLoading] = useState(true)
  const load = () => { setLoading(true); api<T>(path).then(setData).finally(() => setLoading(false)) }
  useEffect(load, deps)
  return { data, loading, reload: load, setData }
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => { const id = setTimeout(onClose, 3500); return () => clearTimeout(id) }, [message])
  return <div className="toast"><Check size={17} />{message}</div>
}

function Modal({ title, subtitle, children, onClose, wide }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className={`modal ${wide ? 'modal-wide' : ''}`}>
      <div className="modal-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-btn" onClick={onClose}><X size={20}/></button></div>
      {children}
    </div>
  </div>
}

function Status({ value }: { value: string }) {
  const labels: Record<string, string> = { connected: '연결됨', unchecked: '확인 전', failed: '실패', success: '성공', running: '실행 중', queued: '대기' }
  return <span className={`status status-${value}`}><i/>{labels[value] || value}</span>
}

function Empty({ title, text, icon: Icon = Database }: { title: string; text: string; icon?: typeof Database }) {
  return <div className="empty"><div className="empty-icon"><Icon size={25}/></div><h3>{title}</h3><p>{text}</p></div>
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('admin@example.com')
  const [password, setPassword] = useState('Admin123!')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<{ access_token: string; user: User }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      localStorage.setItem('metavault_token', result.access_token); onLogin(result.user)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <main className="login-page">
    <section className="login-brand"><div className="brand"><div className="brand-mark"><Database size={22}/></div><b>Meta<span>Vault</span></b></div><div className="login-copy"><p className="eyebrow">ENTERPRISE DATA INTELLIGENCE</p><h1>흩어진 데이터 구조를<br/><em>하나의 자산으로.</em></h1><p>다양한 데이터베이스의 스키마를 안전하게 수집하고,<br/>조직의 데이터 자산을 한곳에서 관리하세요.</p><div className="feature-row"><span><Zap/>자동화 수집</span><span><KeyRound/>다중 인증</span><span><ShieldCheck/>세밀한 권한</span></div></div><div className="orb orb-one"/><div className="orb orb-two"/></section>
    <section className="login-form-wrap"><form className="login-card" onSubmit={submit}><div className="mobile-brand brand"><div className="brand-mark"><Database size={20}/></div><b>Meta<span>Vault</span></b></div><p className="eyebrow">WELCOME BACK</p><h2>관리자 로그인</h2><p className="muted">계속하려면 계정 정보를 입력하세요.</p>{error && <div className="alert"><CircleAlert size={16}/>{error}</div>}<label>이메일 주소<input value={email} onChange={e => setEmail(e.target.value)} type="email" required/></label><label>비밀번호<input value={password} onChange={e => setPassword(e.target.value)} type="password" required/></label><button className="primary login-button" disabled={busy}>{busy ? <RefreshCw className="spin" size={18}/> : <LockKeyhole size={18}/>}로그인</button><p className="login-hint">초기 계정은 환경변수로 변경할 수 있습니다.</p></form></section>
  </main>
}

function Dashboard({ go }: { go: (p: Page) => void }) {
  const { data, loading } = useLoad<any>('/api/dashboard', { sources: 0, active_jobs: 0, objects: 0, failed_runs: 0, recent_runs: [] }, [])
  const cards = [
    ['등록 데이터 소스', data.sources, '개', Database, 'blue'], ['활성 수집 작업', data.active_jobs, '개', CalendarClock, 'violet'],
    ['누적 수집 객체', data.objects, '개', TableProperties, 'mint'], ['실패한 실행', data.failed_runs, '건', CircleAlert, 'coral'],
  ] as const
  return <><PageHead eyebrow="OVERVIEW" title="데이터 운영 현황" description="등록된 데이터 소스와 수집 작업의 상태를 한눈에 확인하세요." action={<button className="primary" onClick={() => go('sources')}><Plus size={17}/>DB 연결 추가</button>}/>
    <div className="stats">{cards.map(([label, value, unit, Icon, color]) => <div className="stat-card" key={label}><div className={`stat-icon ${color}`}><Icon size={21}/></div><div><p>{label}</p><strong>{loading ? '—' : value.toLocaleString()}<small>{unit}</small></strong></div></div>)}</div>
    <div className="grid-2"><section className="panel"><PanelHead title="최근 수집 실행" text="최신 8건의 작업 결과"/><div className="run-list">{data.recent_runs.length ? data.recent_runs.map((run: Run) => <div className="run-row" key={run.id}><div className="run-dot"><Activity size={16}/></div><div><b>수집 작업 #{run.job_id}</b><p>{fmt(run.started_at)} · {run.object_count}개 객체</p></div><Status value={run.status}/></div>) : <Empty title="아직 실행 기록이 없습니다" text="수집 작업을 등록하고 첫 실행을 시작해 보세요." icon={Activity}/>}</div></section>
    <section className="panel quick-panel"><PanelHead title="빠른 시작" text="3단계로 메타데이터 수집을 시작하세요."/><ol className="steps"><li className={data.sources ? 'done' : ''}><span>{data.sources ? <Check/> : '1'}</span><div><b>데이터베이스 연결</b><p>접속 정보와 인증 방식을 등록합니다.</p></div></li><li className={data.active_jobs ? 'done' : ''}><span>{data.active_jobs ? <Check/> : '2'}</span><div><b>수집 스케줄 생성</b><p>대상 스키마와 실행 주기를 지정합니다.</p></div></li><li><span>3</span><div><b>수집 결과 탐색</b><p>스키마와 테이블 구조를 검색합니다.</p></div></li></ol></section></div>
  </>
}

function PageHead({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action}</header>
}
function PanelHead({ title, text, action }: { title: string; text?: string; action?: ReactNode }) { return <div className="panel-head"><div><h3>{title}</h3>{text && <p>{text}</p>}</div>{action}</div> }

function SourceForm({ onClose, onDone, supportedDbTypes }: { onClose: () => void; onDone: () => void; supportedDbTypes: string[] }) {
  const [form,setForm] = useState<any>({ name: '', db_type: 'postgresql', host: 'localhost', port: 5432, database: '', username: '', password: '', ssl_enabled: false, ssl_ca_cert: '', ssl_cert: '', ssl_key: '', ssh_enabled: false, ssh_port: 22, ssh_auth_type: 'private_key' })
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const set = (key: string, value: any) => setForm((f: any) => ({ ...f, [key]: value }))
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setError(''); try { await api('/api/sources', { method: 'POST', body: JSON.stringify(form) }); onDone() } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  return <Modal title="데이터베이스 연결 추가" subtitle="접속 정보는 암호화되어 안전하게 저장됩니다." onClose={onClose} wide><form onSubmit={submit}><div className="form-section"><h4>기본 접속 정보</h4><div className="form-grid"><label>연결 이름<input required placeholder="예: 운영계 PostgreSQL" value={form.name} onChange={e => set('name', e.target.value)}/></label><label>데이터베이스 종류<select value={form.db_type} onChange={e => { const type = e.target.value; setForm({ ...form, db_type: type, port: dbPorts[type] || undefined }) }}>{Object.entries(dbNames).filter(([value]) => supportedDbTypes.includes(value)).map(([v,l]) => <option value={v} key={v}>{l}</option>)}</select></label>{form.db_type === 'sqlite' ? <label className="span-2">DB 파일 경로<input required placeholder="C:\data\sample.db" value={form.database} onChange={e => set('database', e.target.value)}/></label> : <><label>호스트<input required value={form.host} onChange={e => set('host', e.target.value)}/></label><label>포트<input required type="number" value={form.port || ''} onChange={e => set('port', Number(e.target.value))}/></label><label>데이터베이스 / 서비스명<input required value={form.database} onChange={e => set('database', e.target.value)}/></label><label>사용자명<input required value={form.username} onChange={e => set('username', e.target.value)}/></label><label className="span-2">비밀번호<input type="password" value={form.password} onChange={e => set('password', e.target.value)}/></label></>}</div></div>
    {form.db_type !== 'sqlite' && <div className="form-section"><div className="toggle-row"><div><h4>SSL/TLS 암호화</h4><p>인증서 기반으로 안전하게 데이터베이스에 연결합니다. Aiven MySQL은 CA 인증서가 필요합니다.</p></div><button type="button" className={`toggle ${form.ssl_enabled ? 'on' : ''}`} onClick={() => set('ssl_enabled', !form.ssl_enabled)}><i/></button></div>{form.ssl_enabled && <div className="form-grid tunnel"><label className="span-2">CA 인증서 (PEM)<textarea required rows={7} placeholder="-----BEGIN CERTIFICATE-----" value={form.ssl_ca_cert} onChange={e => set('ssl_ca_cert', e.target.value)}/><small>서비스 제공자가 내려받은 CA 인증서 내용을 붙여넣으세요.</small></label><label className="span-2">클라이언트 인증서 (선택)<textarea rows={5} placeholder="-----BEGIN CERTIFICATE-----" value={form.ssl_cert} onChange={e => set('ssl_cert', e.target.value)}/></label><label className="span-2">클라이언트 키 (선택)<textarea rows={5} placeholder="-----BEGIN PRIVATE KEY-----" value={form.ssl_key} onChange={e => set('ssl_key', e.target.value)}/></label></div>}</div>}
    {form.db_type !== 'sqlite' && <div className="form-section"><div className="toggle-row"><div><h4>SSH 터널 사용</h4><p>점프 서버를 통해 사설망 DB에 안전하게 접속합니다.</p></div><button type="button" className={`toggle ${form.ssh_enabled ? 'on' : ''}`} onClick={() => set('ssh_enabled', !form.ssh_enabled)}><i/></button></div>{form.ssh_enabled && <div className="form-grid tunnel"><label>SSH 호스트<input required value={form.ssh_host || ''} onChange={e => set('ssh_host', e.target.value)}/></label><label>SSH 포트<input type="number" value={form.ssh_port} onChange={e => set('ssh_port', Number(e.target.value))}/></label><label>SSH 사용자<input required value={form.ssh_username || ''} onChange={e => set('ssh_username', e.target.value)}/></label><label>인증 방식<select value={form.ssh_auth_type} onChange={e => set('ssh_auth_type', e.target.value)}><option value="private_key">개인키</option><option value="password">비밀번호</option></select></label>{form.ssh_auth_type === 'private_key' ? <><label className="span-2">개인키 (PEM)<textarea required rows={5} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" value={form.ssh_private_key || ''} onChange={e => set('ssh_private_key', e.target.value)}/></label><label className="span-2">키 암호 (선택)<input type="password" value={form.ssh_private_key_passphrase || ''} onChange={e => set('ssh_private_key_passphrase', e.target.value)}/></label></> : <label className="span-2">SSH 비밀번호<input required type="password" value={form.ssh_password || ''} onChange={e => set('ssh_password', e.target.value)}/></label>}</div>}</div>}
    {error && <div className="alert"><CircleAlert size={16}/>{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary" disabled={busy}>{busy && <RefreshCw className="spin" size={16}/>}연결 저장</button></div></form></Modal>
}

function ImportGuide({ onClose }: { onClose: () => void }) {
  const yamlExample = `connections:
  - name: 운영 PostgreSQL
    db_type: postgresql
    host: db.example.com
    port: 5432
    database: production
    username: metadata_reader
    password: \${PROD_DB_PASSWORD}

  - name: 운영 Oracle
    db_type: oracle
    host: oracle.example.com
    port: 1521
    database: ORCL
    username: metadata_reader
    password: \${ORACLE_DB_PASSWORD}
    options:
      service_name: ORCL
    ssh:
      enabled: true
      host: bastion.example.com
      port: 22
      username: deploy
      auth_type: private_key
      private_key: \${BASTION_PRIVATE_KEY}`
  const jsonExample = `{
  "connections": [
    {
      "name": "운영 PostgreSQL",
      "db_type": "postgresql",
      "host": "db.example.com",
      "port": 5432,
      "database": "production",
      "username": "metadata_reader",
      "password": "\${PROD_DB_PASSWORD}"
    }
  ]
}`
  return <Modal title="DB 접속 Import 가이드" subtitle="YAML 또는 JSON으로 여러 연결을 한 번에 등록합니다." onClose={onClose} wide><div className="guide-content"><h4>지원 형식</h4><p><code>connections</code> 배열을 최상위에 두고 각 DB 접속 정보를 입력합니다. 파일 확장자는 <code>.yaml</code>, <code>.yml</code>, <code>.json</code>을 사용하세요.</p><h4>주요 필드</h4><ul><li><b>name</b>, <b>db_type</b>은 필수입니다.</li><li><b>db_type</b>: postgresql, mysql, mariadb, mssql, oracle, sqlite, db2, bigquery</li><li>비밀번호·인증서·개인키는 <code>${'{'}환경변수명{'}'}</code>으로 작성할 수 있습니다.</li><li>SSH 설정은 <code>ssh.enabled</code>, <code>ssh.host</code>, <code>ssh.port</code> 형식으로 작성합니다.</li><li>Import 미리보기에는 비밀번호와 키가 표시되지 않습니다.</li></ul><h4>YAML 예시</h4><pre className="guide-code">{yamlExample}</pre><h4>JSON 예시</h4><pre className="guide-code">{jsonExample}</pre></div></Modal>
}

function SourceImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (message: string) => void }) {
  const [file, setFile] = useState<File|null>(null); const [preview, setPreview] = useState<any>(null); const [duplicate, setDuplicate] = useState('skip'); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const request = async (path: string) => { if (!file) throw new Error('Import할 YAML 또는 JSON 파일을 선택하세요.'); const form = new FormData(); form.append('file', file); const token = localStorage.getItem('metavault_token'); const response = await fetch(`${path}${path.endsWith('/import')?`?duplicate=${duplicate}`:''}`, { method:'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form }); const body = await response.json().catch(()=>({})); if (!response.ok) throw new Error(body.detail || 'Import 요청에 실패했습니다.'); return body }
  const selectFile = async (value: File|null) => { setFile(value); setPreview(null); setError(''); if (!value) return; setBusy(true); try { setPreview(await request('/api/sources/import/preview')) } catch(e) { setError((e as Error).message) } finally { setBusy(false) } }
  const submit = async () => { setBusy(true); setError(''); try { const result=await request('/api/sources/import'); onDone(`DB 접속 Import 완료: ${result.created}개 등록, ${result.updated}개 수정, ${result.skipped}개 건너뜀`) } catch(e) { setError((e as Error).message) } finally { setBusy(false) } }
  return <Modal title="DB 접속 일괄 Import" subtitle="YAML 또는 JSON 파일을 미리 확인한 뒤 등록합니다." onClose={onClose} wide><div className="import-content"><label className="file-drop"><Upload size={22}/><b>{file ? file.name : 'YAML 또는 JSON 파일을 선택하세요'}</b><small>최대 2MB · .yaml, .yml, .json</small><input type="file" accept=".yaml,.yml,.json,application/json,text/yaml" onChange={e=>selectFile(e.target.files?.[0]||null)}/></label>{busy&&!preview&&<Loading/>}{preview&&<><div className="import-summary"><b>{preview.total}개 항목</b><span className="tag">정상 {preview.valid}개</span>{preview.errors.length>0&&<span className="tag error-tag">오류 {preview.errors.length}개</span>}</div>{preview.items.length>0&&<div className="import-preview"><table><thead><tr><th>이름</th><th>DB 종류</th><th>호스트</th><th>포트</th><th>데이터베이스</th><th>SSH</th></tr></thead><tbody>{preview.items.map((item:any)=><tr key={`${item.name}-${item.host}`}><td>{item.name}</td><td>{item.db_type}</td><td>{item.host}</td><td>{item.port||'—'}</td><td>{item.database||'—'}</td><td>{item.ssh_enabled?'사용':'—'}</td></tr>)}</tbody></table></div>}{preview.errors.length>0&&<div className="import-errors">{preview.errors.map((item:any)=><p key={item.row}>행 {item.row}: {item.error}</p>)}</div>}<label>중복 이름 처리<select value={duplicate} onChange={e=>setDuplicate(e.target.value)}><option value="skip">건너뛰기</option><option value="overwrite">기존 연결 덮어쓰기</option><option value="rename">이름 뒤에 번호 붙이기</option></select></label></>}</div>{error&&<div className="alert"><CircleAlert size={16}/>{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button type="button" className="primary" disabled={!preview||!preview.valid||busy} onClick={submit}>{busy&&<RefreshCw className="spin" size={16}/>}Import 실행</button></div></Modal>
}

function Sources({ toast }: { toast: (m: string) => void }) {
  const { data, loading, reload } = useLoad<Source[]>('/api/sources', [], [])
  const capabilities = useLoad<Capabilities>('/api/capabilities', { deployment_mode: 'local', supported_db_types: Object.keys(dbNames), excluded_db_types: [] }, [])
  const [open, setOpen] = useState(false); const [importOpen, setImportOpen] = useState(false); const [guideOpen, setGuideOpen] = useState(false); const [query, setQuery] = useState('')
  const filtered = data.filter(s => `${s.name} ${s.host} ${s.database}`.toLowerCase().includes(query.toLowerCase()))
  const test = async (id: number) => { try { await api(`/api/sources/${id}/test`, { method: 'POST' }); toast('데이터베이스 연결에 성공했습니다.'); reload() } catch(e) { toast((e as Error).message) } }
  const remove = async (id: number) => { if (!confirm('데이터 소스와 연결된 수집 작업을 삭제할까요?')) return; await api(`/api/sources/${id}`, { method: 'DELETE' }); reload() }
  return <><PageHead eyebrow="DATA MANAGEMENT" title="DB 접속 관리" description="메타데이터를 수집할 데이터베이스 연결과 인증 방식을 관리합니다." action={<div className="source-actions"><button className="ghost" onClick={()=>setGuideOpen(true)}><BookOpen size={16}/>Import 가이드</button><button className="ghost" onClick={()=>setImportOpen(true)}><Upload size={16}/>일괄 Import</button><button className="primary" onClick={() => setOpen(true)}><Plus size={17}/>새 연결</button></div>}/>
    <section className="panel"><div className="toolbar"><div className="search"><Search size={17}/><input placeholder="연결 이름, 호스트 검색" value={query} onChange={e => setQuery(e.target.value)}/></div><span className="count">총 {data.length}개 연결</span></div>{loading ? <Loading/> : filtered.length ? <div className="cards">{filtered.map(s => <article className="source-card" key={s.id}><div className="source-top"><div className={`db-logo db-${s.db_type}`}>{dbNames[s.db_type]?.slice(0,2) || 'DB'}</div><div><h3>{s.name}</h3><p>{dbNames[s.db_type]}</p></div><Status value={s.status}/></div><dl><div><dt>엔드포인트</dt><dd>{s.db_type === 'sqlite' ? s.database : `${s.host}:${s.port}`}</dd></div><div><dt>데이터베이스</dt><dd>{s.database || '—'}</dd></div><div><dt>인증</dt><dd>{s.ssh_enabled ? <><KeyRound size={14}/> SSH {s.ssh_auth_type === 'private_key' ? '개인키' : '비밀번호'}</> : <><LockKeyhole size={14}/> DB 인증</>}</dd></div><div><dt>최근 테스트</dt><dd>{fmt(s.last_tested_at)}</dd></div></dl><div className="card-actions"><button onClick={() => test(s.id)}><Zap size={15}/>연결 테스트</button><button className="danger-icon" onClick={() => remove(s.id)} title="삭제"><Trash2 size={16}/></button></div></article>)}</div> : <Empty title="등록된 데이터베이스가 없습니다" text="새 연결을 추가하면 스키마 메타데이터 수집을 시작할 수 있습니다."/>}</section>{open && <SourceForm supportedDbTypes={capabilities.data.supported_db_types.filter(type => dbNames[type])} onClose={() => setOpen(false)} onDone={() => { setOpen(false); reload(); toast('데이터베이스 연결을 저장했습니다.') }}/>} {importOpen&&<SourceImportDialog onClose={()=>setImportOpen(false)} onDone={message=>{setImportOpen(false);reload();toast(message)}}/>} {guideOpen&&<ImportGuide onClose={()=>setGuideOpen(false)}/>}</>
}

const COLLECTION_OPTIONS: [string, string][] = [['INDEX','인덱스'],['TABLE','테이블'],['VIEW','뷰'],['PROCEDURE','프로시저'],['SELECT PRIVILEGE','조회 권한'],['TRIGGER','트리거'],['TABLE PARTITION','테이블 파티션'],['INDEX PARTITION','인덱스 파티션'],['TABLE SUBPARTITION','테이블 서브파티션'],['INDEX SUBPARTITION','인덱스 서브파티션'],['MVIEW','Materialized View'],['SEQUENCE','시퀀스'],['DATABASE LINK','Database Link'],['SYNONYM','Synonym']]

function JobForm({ sources, onClose, onDone, job }: { sources: Source[]; onClose: () => void; onDone: () => void; job?: Job }) {
  const [form, setForm] = useState<any>(() => job ? {...job, collection_items: job.collection_items?.length ? job.collection_items : COLLECTION_OPTIONS.map(([key])=>key)} : { name: '', data_source_id: sources[0]?.id || '', schedule_type: 'cron', cron: '0 2 * * *', interval_minutes: 60, schemas: [], collection_items: ['INDEX','TABLE','VIEW','PROCEDURE','SELECT PRIVILEGE'], collect_storage: false, is_active: true }); const [error,setError]=useState('')
  const submit = async (e: FormEvent) => { e.preventDefault(); try { await api(job ? `/api/jobs/${job.id}` : '/api/jobs',{method:job?'PUT':'POST',body:JSON.stringify(form)}); onDone() } catch(e){setError((e as Error).message)} }

  return <Modal title={job?'수집 스케줄 수정':'수집 스케줄 생성'} subtitle="실행 주기와 수집할 메타데이터 범위를 지정하세요." onClose={onClose}><form onSubmit={submit}><div className="form-section"><div className="form-grid one"><label>작업 이름<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="예: 운영계 매일 수집"/></label><label>데이터 소스<select required value={form.data_source_id} onChange={e=>setForm({...form,data_source_id:Number(e.target.value)})}><option value="">선택하세요</option>{sources.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label><label>수집 옵션<select value={form.collect_storage?'storage':'basic'} onChange={e=>setForm({...form,collect_storage:e.target.value==='storage'})}><option value="basic">기본 메타데이터 수집</option><option value="storage">기본 + 스토리지 증가량 수집</option></select><small>스토리지 옵션은 테이블·인덱스 용량과 이전 수집 대비 증감량을 기록합니다.</small></label><fieldset className="collection-items"><legend>수집 객체 유형</legend><div className="collection-item-actions"><button type="button" className="ghost" onClick={()=>setForm({...form,collection_items:COLLECTION_OPTIONS.map(([key])=>key)})}>전체 선택</button><button type="button" className="ghost" onClick={()=>setForm({...form,collection_items:[]})}>전체 해제</button></div><div className="item-check-grid">{COLLECTION_OPTIONS.map(([key,label])=><label className="check" key={key}><input type="checkbox" checked={form.collection_items.includes(key)} onChange={e=>setForm({...form,collection_items:e.target.checked?[...form.collection_items,key]:form.collection_items.filter((x:string)=>x!==key)})}/><span><Check/></span>{label}</label>)}</div><small>선택한 객체만 다음 수집부터 저장합니다. 파티션 등은 DB 종류에 따라 결과가 없을 수 있습니다.</small></fieldset><label>실행 방식<select value={form.schedule_type} onChange={e=>setForm({...form,schedule_type:e.target.value})}><option value="cron">Cron 스케줄</option><option value="interval">주기 실행</option><option value="manual">수동 실행만</option></select></label>{form.schedule_type==='cron'&&<label>Cron 표현식<input required value={form.cron} onChange={e=>setForm({...form,cron:e.target.value})}/><small>분 시 일 월 요일 — 예: 매일 새벽 2시 = 0 2 * * *</small></label>}{form.schedule_type==='interval'&&<label>실행 간격 (분)<input type="number" min="1" value={form.interval_minutes} onChange={e=>setForm({...form,interval_minutes:Number(e.target.value)})}/></label>}<label>대상 스키마 (선택)<input value={form.schemas.join(', ')} placeholder="public, sales — 비우면 시스템 스키마 제외 전체" onChange={e=>setForm({...form,schemas:e.target.value.split(',').map(x=>x.trim()).filter(Boolean)})}/></label></div></div>{error&&<div className="alert">{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary">스케줄 저장</button></div></form></Modal>
}

function JobImportGuide({ onClose }: { onClose: () => void }) {
  const example = `jobs:
  - name: 운영 DB 매일 수집
    data_source: 운영 PostgreSQL
    schedule_type: cron
    cron: "0 2 * * *"
    schemas:
      - public
    collection_items:
      - TABLE
      - VIEW
      - INDEX
      - SELECT PRIVILEGE
    collect_storage: true
    is_active: true`
  return <Modal title="수집 스케줄 Import 가이드" subtitle="YAML 또는 JSON으로 여러 스케줄을 한 번에 등록합니다." onClose={onClose} wide><div className="guide-content"><h4>필수 필드</h4><ul><li><b>name</b>: 수집 작업 이름</li><li><b>data_source</b>: DB 접속 관리에 등록된 연결 이름 또는 <b>data_source_id</b></li><li><b>schedule_type</b>: cron, interval, manual 중 하나</li><li><b>cron</b>: cron 방식의 실행 표현식</li><li><b>interval_minutes</b>: interval 방식의 실행 간격(분)</li></ul><h4>YAML 예시</h4><pre className="guide-code">{example}</pre><p>중복 이름은 Import 화면에서 건너뛰기, 덮어쓰기, 이름 변경 중 선택합니다. 수집 항목은 현재 지원되는 작업 옵션을 그대로 사용합니다.</p></div></Modal>
}

function JobImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (message: string) => void }) {
  const [file,setFile]=useState<File|null>(null); const [preview,setPreview]=useState<any>(null); const [duplicate,setDuplicate]=useState('skip'); const [busy,setBusy]=useState(false); const [error,setError]=useState('')
  const request=async(path:string)=>{if(!file)throw new Error('Import할 YAML 또는 JSON 파일을 선택하세요.');const form=new FormData();form.append('file',file);const token=localStorage.getItem('metavault_token');const url=`${path}${path.endsWith('/import')?`?duplicate=${duplicate}`:''}`;const response=await fetch(url,{method:'POST',headers:token?{Authorization:`Bearer ${token}`}:{},body:form});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Import 요청에 실패했습니다.');return body}
  const selectFile=async(value:File|null)=>{setFile(value);setPreview(null);setError('');if(!value)return;setBusy(true);try{setPreview(await request('/api/jobs/import/preview'))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const submit=async()=>{setBusy(true);setError('');try{const result=await request('/api/jobs/import');onDone(`스케줄 Import 완료: ${result.created}개 등록, ${result.updated}개 수정, ${result.skipped}개 건너뜀`)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <Modal title="수집 스케줄 일괄 Import" subtitle="YAML 또는 JSON 파일을 미리 확인한 뒤 등록합니다." onClose={onClose} wide><div className="import-content"><label className="file-drop"><Upload size={22}/><b>{file?file.name:'YAML 또는 JSON 파일을 선택하세요'}</b><small>최대 2MB · .yaml, .yml, .json</small><input type="file" accept=".yaml,.yml,.json,application/json,text/yaml" onChange={e=>selectFile(e.target.files?.[0]||null)}/></label>{busy&&!preview&&<Loading/>}{preview&&<><div className="import-summary"><b>{preview.total}개 스케줄</b><span className="tag">정상 {preview.valid}개</span>{preview.errors.length>0&&<span className="tag error-tag">오류 {preview.errors.length}개</span>}</div>{preview.items.length>0&&<div className="import-preview"><table><thead><tr><th>작업 이름</th><th>데이터 소스</th><th>방식</th><th>Cron</th><th>수집 항목</th></tr></thead><tbody>{preview.items.map((item:any)=><tr key={`${item.name}-${item.data_source}`}><td>{item.name}</td><td>{item.data_source}</td><td>{item.schedule_type}</td><td>{item.cron||'—'}</td><td>{item.collection_items?.join(', ')||'—'}</td></tr>)}</tbody></table></div>}{preview.errors.length>0&&<div className="import-errors">{preview.errors.map((item:any)=><p key={item.row}>행 {item.row}: {item.error}</p>)}</div>}<label>중복 이름 처리<select value={duplicate} onChange={e=>setDuplicate(e.target.value)}><option value="skip">건너뛰기</option><option value="overwrite">기존 스케줄 덮어쓰기</option><option value="rename">이름 뒤에 번호 붙이기</option></select></label></>}</div>{error&&<div className="alert"><CircleAlert size={16}/>{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button type="button" className="primary" disabled={!preview||!preview.valid||busy} onClick={submit}>{busy&&<RefreshCw className="spin" size={16}/>}Import 실행</button></div></Modal>
}

function Jobs({ toast }: { toast: (m:string)=>void }) {
  const jobs=useLoad<Job[]>('/api/jobs',[],[]), sources=useLoad<Source[]>('/api/sources',[],[]), runs=useLoad<Run[]>('/api/runs',[],[]); const [open,setOpen]=useState(false); const [editing,setEditing]=useState<Job|null>(null); const [importOpen,setImportOpen]=useState(false); const [guideOpen,setGuideOpen]=useState(false)
  const sourceName=(id:number)=>sources.data.find(s=>s.id===id)?.name||`#${id}`
  const run=async(id:number)=>{await api(`/api/jobs/${id}/run`,{method:'POST'});toast('수집 작업을 시작했습니다.');setTimeout(runs.reload,900)}
  const remove=async(id:number)=>{if(confirm('이 수집 작업과 실행 기록을 삭제할까요?')){await api(`/api/jobs/${id}`,{method:'DELETE'});jobs.reload()}}
  return <><PageHead eyebrow="AUTOMATION" title="수집 스케줄" description="스키마 수집 작업의 실행 주기와 결과를 관리합니다." action={<div className="source-actions"><button className="ghost" onClick={()=>setGuideOpen(true)}><BookOpen size={16}/>Import 가이드</button><button className="ghost" disabled={!sources.data.length} onClick={()=>setImportOpen(true)}><Upload size={16}/>일괄 Import</button><button className="primary" disabled={!sources.data.length} onClick={()=>setOpen(true)}><Plus size={17}/>스케줄 생성</button></div>}/><section className="panel table-panel"><div className="responsive-table"><table><thead><tr><th>작업 이름</th><th>데이터 소스</th><th>수집 옵션</th><th>스케줄</th><th>다음 실행</th><th>상태</th><th></th></tr></thead><tbody>{jobs.data.map(j=><tr key={j.id}><td><b>{j.name}</b><small>스키마 {j.schemas.length?j.schemas.join(', '):'전체'}</small></td><td>{sourceName(j.data_source_id)}</td><td><span className="tag">{j.collect_storage?'스토리지 증가량':'기본'}</span>{j.collection_items?.length>0&&<small className="job-items">{j.collection_items.join(', ')}</small>}</td><td><code>{j.schedule_type==='cron'?j.cron:j.schedule_type==='interval'?`${j.interval_minutes}분마다`:'수동'}</code></td><td>{fmt(j.next_run_at)}</td><td><span className={`status ${j.is_active?'status-success':'status-unchecked'}`}><i/>{j.is_active?'활성':'비활성'}</span></td><td className="row-actions"><button title="수정" onClick={()=>{setEditing(j);setOpen(true)}}><Pencil size={15}/></button><button title="지금 실행" onClick={()=>run(j.id)}><Play size={15}/></button><button title="삭제" onClick={()=>remove(j.id)}><Trash2 size={15}/></button></td></tr>)}</tbody></table>{!jobs.data.length&&<Empty title="수집 스케줄이 없습니다" text={sources.data.length?'첫 수집 스케줄을 생성해 보세요.':'먼저 데이터베이스 연결을 등록해 주세요.'} icon={CalendarClock}/>}</div></section><section className="panel"><PanelHead title="실행 이력" text="최근 100건" action={<button className="icon-btn" onClick={runs.reload}><RefreshCw size={16}/></button>}/><div className="run-list compact">{runs.data.map(r=><div className="run-row" key={r.id}><div className="run-dot"><Activity size={15}/></div><div><b>{jobs.data.find(j=>j.id===r.job_id)?.name||`작업 #${r.job_id}`}</b><p>{fmt(r.started_at)} · {r.object_count}개 객체 {r.error_message&&`· ${r.error_message}`}</p></div><Status value={r.status}/></div>)}{!runs.data.length&&<p className="inline-empty">아직 실행 이력이 없습니다.</p>}</div></section>{open&&<JobForm job={editing||undefined} sources={sources.data} onClose={()=>{setOpen(false);setEditing(null)}} onDone={()=>{setOpen(false);setEditing(null);jobs.reload();toast(editing?'수집 스케줄을 수정했습니다.':'수집 스케줄을 생성했습니다.')}}/>}{importOpen&&<JobImportDialog onClose={()=>setImportOpen(false)} onDone={message=>{setImportOpen(false);jobs.reload();toast(message)}}/>}{guideOpen&&<JobImportGuide onClose={()=>setGuideOpen(false)}/>}</>
}

const EXPORT_OPTIONS: [string, string][] = [['SUMMARY','요약'],['TABLE','테이블'],['COLUMN','컬럼'],['VIEW','뷰'],['INDEX','인덱스'],['FOREIGN KEY','외래키'],['PROCEDURE','프로시저/함수'],['SELECT PRIVILEGE','조회 권한'],['STORAGE','스토리지']]

function ExportDialog({ onClose, onDownload }: { onClose: () => void; onDownload: (items: string[]) => Promise<void> }) {
  const [items, setItems] = useState(EXPORT_OPTIONS.map(([key]) => key)); const [error, setError] = useState('')
  const submit = async () => { if (!items.length) { setError('다운로드할 항목을 하나 이상 선택하세요.'); return } try { await onDownload(items) } catch (e) { setError((e as Error).message) } }
  return <Modal title="Excel 다운로드" subtitle="다운로드할 수집 항목을 선택하세요." onClose={onClose}><div className="export-dialog"><div className="collection-item-actions"><button type="button" className="ghost" onClick={()=>setItems(EXPORT_OPTIONS.map(([key])=>key))}>전체 선택</button><button type="button" className="ghost" onClick={()=>setItems([])}>전체 해제</button></div><div className="item-check-grid">{EXPORT_OPTIONS.map(([key,label])=><label className="check" key={key}><input type="checkbox" checked={items.includes(key)} onChange={e=>setItems(e.target.checked?[...items,key]:items.filter(item=>item!==key))}/><span><Check/></span>{label}</label>)}</div>{error&&<div className="alert">{error}</div>}</div><div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button type="button" className="primary" disabled={!items.length} onClick={submit}><Download size={16}/>다운로드</button></div></Modal>
}

function Metadata() {
  const {data,loading}=useLoad<any[]>('/api/metadata',[],[]); const [selected,setSelected]=useState<number|null>(null); const [query,setQuery]=useState(''); const [exportOpen,setExportOpen]=useState(false); const current=data.find(x=>x.id===(selected||data[0]?.id));
  const tables=useMemo(()=>current?.payload.schemas.flatMap((s:any)=>(s.tables||[]).map((t:any)=>({...t,schema:s.name})))||[],[current]); const views=useMemo(()=>current?.payload.schemas.flatMap((s:any)=>(s.views||[]).map((v:any)=>({...v,schema:s.name})))||[],[current]); const procedures=useMemo(()=>current?.payload.schemas.flatMap((s:any)=>(s.procedures||[]).map((p:any)=>({...p,schema:s.name})))||[],[current]); const filtered=tables.filter((t:any)=>`${t.schema}.${t.name}`.toLowerCase().includes(query.toLowerCase()))
  const download = async (items: string[]) => {
    if (!current) return
    const token = localStorage.getItem('metavault_token')
    const params = new URLSearchParams({ items: items.join(',') })
    const response = await fetch(`/api/metadata/${current.id}/export.xlsx?${params.toString()}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (!response.ok) throw new Error('Excel 다운로드에 실패했습니다.')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `MetaVault_${current.payload.source || 'schema'}.xlsx`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <><PageHead eyebrow="DATA MANAGEMENT" title="스키마 정보" description="수집된 데이터베이스 구조와 컬럼 정보를 탐색합니다." action={current&&<button className="primary" onClick={()=>setExportOpen(true)}><Download size={17}/>Excel 다운로드</button>}/><div className="metadata-layout"><aside className="panel source-tree"><h3>데이터 소스</h3>{data.map(x=><button className={current?.id===x.id?'active':''} onClick={()=>setSelected(x.id)} key={x.id}><Database size={17}/><span><b>{x.payload.source}</b><small>{x.payload.db_type} · {fmt(x.captured_at)}</small></span><ChevronDown size={15}/></button>)}{!data.length&&!loading&&<p>수집된 정보 없음</p>}</aside><section className="panel metadata-main">{current?<><div className="toolbar"><div><h3>{current.payload.source}</h3><p>{current.payload.schemas.length}개 스키마 · {tables.length}개 테이블 · {views.length}개 뷰 · {procedures.length}개 프로시저{current.payload.storage_summary&&` · 총 ${fmtBytes(current.payload.storage_summary.total_bytes)} · 증감 ${fmtBytes(current.payload.storage_summary.growth_bytes)}`}</p></div><div className="search"><Search size={17}/><input placeholder="스키마, 테이블 검색" value={query} onChange={e=>setQuery(e.target.value)}/></div></div>{views.length>0&&<section className="object-panel"><h3>뷰 및 조회 권한</h3>{views.map((view:any)=><div className="object-row" key={`${view.schema}.${view.name}`}><div><b>{view.name}</b><small>{view.schema}</small></div><span className={`permission ${view.permissions?.select===null?'unchecked':view.permissions?.select?'allowed':'denied'}`}>{view.permissions?.select===null?'SELECT 권한 미수집':view.permissions?.select?'SELECT 가능':'SELECT 권한 없음'}</span></div>)}</section>}{procedures.length>0&&<section className="object-panel"><h3>프로시저 및 함수</h3>{procedures.map((procedure:any)=><div className="object-row" key={`${procedure.schema}.${procedure.name}`}><div><b>{procedure.name}</b><small>{procedure.schema} · {procedure.routine_type||'ROUTINE'}</small></div></div>)}</section>}<div className="schema-list">{filtered.map((table:any)=><details key={`${table.schema}.${table.name}`}><summary><div className="table-icon"><TableProperties size={16}/></div><div><b>{table.name}</b><small>{table.schema} · {table.columns.length} columns · 인덱스 {table.indexes?.length||0}개</small></div><span className={`permission ${table.permissions?.select===null?'unchecked':table.permissions?.select?'allowed':'denied'}`}>{table.permissions?.select===null?'조회 권한 미수집':table.permissions?.select?'조회 가능':'조회 권한 없음'}</span>{table.storage?.growth_bytes!=null&&<span className={`growth ${table.storage.growth_bytes>0?'up':table.storage.growth_bytes<0?'down':''}`}>{table.storage.growth_bytes>0?'+':''}{fmtBytes(table.storage.growth_bytes)}</span>}<ChevronDown size={16}/></summary>{table.storage&&<div className="storage-bar"><span><small>데이터</small><b>{fmtBytes(table.storage.data_bytes)}</b></span><span><small>인덱스</small><b>{fmtBytes(table.storage.index_bytes)}</b></span><span><small>전체</small><b>{fmtBytes(table.storage.total_bytes)}</b></span><span><small>이전 대비</small><b>{table.storage.growth_bytes==null?'기준값':`${table.storage.growth_bytes>0?'+':''}${fmtBytes(table.storage.growth_bytes)}`}</b></span><span><small>예상 행 수</small><b>{table.storage.row_estimate?.toLocaleString()??'—'}</b></span></div>}<div className="columns"><div className="column-head"><span>컬럼</span><span>타입</span><span>NULL</span><span>키</span></div>{table.columns.map((c:any)=><div className="column-row" key={c.name}><span><b>{c.name}</b>{c.comment&&<small>{c.comment}</small>}</span><code>{c.type}</code><span>{c.nullable?'YES':'NO'}</span><span>{table.primary_key?.constrained_columns?.includes(c.name)?<span className="key"><KeyRound size={12}/>PK</span>:'—'}</span></div>)}</div>{table.indexes?.length>0&&<div className="index-list"><b>인덱스</b>{table.indexes.map((index:any)=><span key={index.name}>{index.name}{index.unique?' · UNIQUE':''}</span>)}</div>}</details>)}</div></>:<Empty title="수집된 스키마 정보가 없습니다" text="수집 스케줄을 실행하면 데이터 자산을 여기서 탐색할 수 있습니다." icon={TableProperties}/>}</section></div>{exportOpen&&<ExportDialog onClose={()=>setExportOpen(false)} onDownload={async items=>{await download(items);setExportOpen(false)}}/>}</>
}

function PasswordChange({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError('')
    if (form.new_password !== form.confirm_password) { setError('새 비밀번호가 일치하지 않습니다.'); return }
    setBusy(true)
    try { await api('/api/auth/password', { method: 'POST', body: JSON.stringify({ current_password: form.current_password, new_password: form.new_password }) }); onClose() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <Modal title="비밀번호 변경" subtitle="현재 비밀번호를 확인한 뒤 새 비밀번호로 변경합니다." onClose={onClose}><form onSubmit={submit}><div className="form-section"><div className="form-grid one"><label>현재 비밀번호<input required type="password" value={form.current_password} onChange={e=>setForm({...form,current_password:e.target.value})}/></label><label>새 비밀번호<input required minLength={8} type="password" value={form.new_password} onChange={e=>setForm({...form,new_password:e.target.value})}/><small>8자 이상 입력하세요.</small></label><label>새 비밀번호 확인<input required minLength={8} type="password" value={form.confirm_password} onChange={e=>setForm({...form,confirm_password:e.target.value})}/></label></div></div>{error&&<div className="alert"><CircleAlert size={16}/>{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary" disabled={busy}>{busy&&<RefreshCw className="spin" size={16}/>}비밀번호 변경</button></div></form></Modal>
}

function UserForm({roles,onClose,onDone}:{roles:Role[];onClose:()=>void;onDone:()=>void}){const[form,setForm]=useState<any>({email:'',name:'',password:'',is_active:true,role_ids:[]});const submit=async(e:FormEvent)=>{e.preventDefault();await api('/api/admin/users',{method:'POST',body:JSON.stringify(form)});onDone()};return <Modal title="사용자 추가" onClose={onClose}><form onSubmit={submit}><div className="form-section"><div className="form-grid one"><label>이름<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>이메일<input required type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label><label>초기 비밀번호<input required type="password" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></label><fieldset><legend>역할</legend>{roles.map(r=><label className="check" key={r.id}><input type="checkbox" onChange={e=>setForm({...form,role_ids:e.target.checked?[...form.role_ids,r.id]:form.role_ids.filter((x:number)=>x!==r.id)})}/><span><Check/></span>{r.name}</label>)}</fieldset></div></div><div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary">사용자 저장</button></div></form></Modal>}

function UsersPage({toast}:{toast:(m:string)=>void}){const users=useLoad<User[]>('/api/admin/users',[],[]),roles=useLoad<Role[]>('/api/admin/roles',[],[]);const[open,setOpen]=useState(false);const remove=async(id:number,name:string)=>{if(!confirm(`${name} 사용자를 삭제할까요? 삭제한 사용자는 복구할 수 없습니다.`))return;try{await api(`/api/admin/users/${id}`,{method:'DELETE'});users.reload();toast('사용자를 삭제했습니다.')}catch(e){toast((e as Error).message)}};return <><PageHead eyebrow="ADMINISTRATION" title="사용자 관리" description="관리 콘솔에 접근할 사용자와 활성 상태를 관리합니다." action={<button className="primary" onClick={()=>setOpen(true)}><Plus size={17}/>사용자 추가</button>}/><section className="panel table-panel"><div className="responsive-table"><table><thead><tr><th>사용자</th><th>역할</th><th>상태</th><th>등록일</th><th></th></tr></thead><tbody>{users.data.map(u=><tr key={u.id}><td><div className="user-cell"><span>{u.name.slice(0,1)}</span><div><b>{u.name}</b><small>{u.email}</small></div></div></td><td>{u.roles.map(r=><span className="tag" key={r}>{r}</span>)}</td><td><span className={`status ${u.is_active?'status-success':'status-failed'}`}><i/>{u.is_active?'활성':'중지'}</span></td><td>—</td><td className="row-actions"><button title="사용자 삭제" onClick={()=>remove(u.id,u.name)}><Trash2 size={15}/></button></td></tr>)}</tbody></table></div></section>{open&&<UserForm roles={roles.data} onClose={()=>setOpen(false)} onDone={()=>{setOpen(false);users.reload();toast('사용자를 추가했습니다.')}}/>}</>}

function RoleForm({permissions,menus,onClose,onDone}:{permissions:Permission[];menus:Menu[];onClose:()=>void;onDone:()=>void}){const[form,setForm]=useState<any>({name:'',description:'',permission_ids:[],menu_ids:[]});const toggle=(key:string,id:number,on:boolean)=>setForm({...form,[key]:on?[...form[key],id]:form[key].filter((x:number)=>x!==id)});const submit=async(e:FormEvent)=>{e.preventDefault();await api('/api/admin/roles',{method:'POST',body:JSON.stringify(form)});onDone()};return <Modal title="새 역할 만들기" subtitle="기능 권한과 노출할 메뉴를 함께 지정합니다." onClose={onClose} wide><form onSubmit={submit}><div className="form-section"><div className="form-grid"><label>역할 이름<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>설명<input value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label></div></div><div className="permission-grid"><fieldset><legend>기능 권한</legend>{permissions.map(p=><label className="check permission" key={p.id}><input type="checkbox" onChange={e=>toggle('permission_ids',p.id,e.target.checked)}/><span><Check/></span><div><b>{p.code}</b><small>{p.description}</small></div></label>)}</fieldset><fieldset><legend>노출 메뉴</legend>{menus.map(m=><label className="check permission" key={m.id}><input type="checkbox" onChange={e=>toggle('menu_ids',m.id,e.target.checked)}/><span><Check/></span><div><b>{m.label}</b><small>{m.path}</small></div></label>)}</fieldset></div><div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary">역할 저장</button></div></form></Modal>}

function MenuForm({onClose,onDone}:{onClose:()=>void;onDone:()=>void}){const[form,setForm]=useState({code:'',label:'',path:'/',icon:'Circle',order:10,parent_id:null});const submit=async(e:FormEvent)=>{e.preventDefault();await api('/api/admin/menus',{method:'POST',body:JSON.stringify(form)});onDone()};return <Modal title="메뉴 추가" subtitle="역할에 배정할 관리 콘솔 메뉴를 등록합니다." onClose={onClose}><form onSubmit={submit}><div className="form-section"><div className="form-grid"><label>메뉴 코드<input required value={form.code} onChange={e=>setForm({...form,code:e.target.value})} placeholder="audit"/></label><label>메뉴명<input required value={form.label} onChange={e=>setForm({...form,label:e.target.value})} placeholder="감사 로그"/></label><label>경로<input required value={form.path} onChange={e=>setForm({...form,path:e.target.value})} placeholder="/audit"/></label><label>정렬 순서<input type="number" value={form.order} onChange={e=>setForm({...form,order:Number(e.target.value)})}/></label></div></div><div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>취소</button><button className="primary">메뉴 저장</button></div></form></Modal>}

function RolesPage({toast}:{toast:(m:string)=>void}){const roles=useLoad<Role[]>('/api/admin/roles',[],[]),permissions=useLoad<Permission[]>('/api/admin/permissions',[],[]),menus=useLoad<Menu[]>('/api/admin/menus',[],[]);const[open,setOpen]=useState(false);const[menuOpen,setMenuOpen]=useState(false);return <><PageHead eyebrow="ADMINISTRATION" title="역할 및 권한" description="역할별 기능 권한과 접근 가능한 메뉴를 구성합니다." action={<button className="primary" onClick={()=>setOpen(true)}><Plus size={17}/>역할 추가</button>}/><div className="role-grid">{roles.data.map(r=><article className="panel role-card" key={r.id}><div className="role-icon"><ShieldCheck size={22}/></div><h3>{r.name}</h3><p>{r.description||'설명 없음'}</p><div className="role-counts"><span><b>{r.permissions.length}</b> 기능 권한</span><span><b>{r.menus.length}</b> 접근 메뉴</span></div><div className="role-tags">{r.permissions.slice(0,4).map(id=><span className="tag" key={id}>{permissions.data.find(p=>p.id===id)?.code}</span>)}{r.permissions.length>4&&<span className="tag">+{r.permissions.length-4}</span>}</div></article>)}</div><section className="panel menu-panel"><PanelHead title="메뉴 구성" text="역할별로 노출할 메뉴 목록" action={<button className="ghost" onClick={()=>setMenuOpen(true)}><Plus size={15}/>메뉴 추가</button>}/><div className="menu-list">{menus.data.map(m=><div key={m.id}><span>{m.order}</span><div><b>{m.label}</b><small>{m.code}</small></div><code>{m.path}</code></div>)}</div></section>{open&&<RoleForm permissions={permissions.data} menus={menus.data} onClose={()=>setOpen(false)} onDone={()=>{setOpen(false);roles.reload();toast('새 역할을 만들었습니다.')}}/>}{menuOpen&&<MenuForm onClose={()=>setMenuOpen(false)} onDone={()=>{setMenuOpen(false);menus.reload();toast('메뉴를 추가했습니다.')}}/>}</>}

function Loading(){return <div className="loading"><RefreshCw className="spin"/>불러오는 중...</div>}

export default function App() {
  const [user,setUser]=useState<User|null>(null); const [checking,setChecking]=useState(true); const [page,setPage]=useState<Page>(()=>(location.hash.slice(1) as Page)||'dashboard'); const [mobile,setMobile]=useState(false); const [toast,setToast]=useState(''); const [passwordOpen,setPasswordOpen]=useState(false)
  useEffect(()=>{const token=localStorage.getItem('metavault_token');if(!token){setChecking(false);return}api<User>('/api/auth/me').then(setUser).catch(()=>localStorage.removeItem('metavault_token')).finally(()=>setChecking(false))},[])
  useEffect(()=>{location.hash=page},[page]); if(checking)return <Loading/>; if(!user)return <Login onLogin={setUser}/>
  const visible=nav.filter(n=>user.menus.includes(n.id)||user.permissions.includes('admin:*')); const select=(p:Page)=>{setPage(p);setMobile(false)}; const groups=[...new Set(visible.map(n=>n.group))]
  const logout=()=>{localStorage.removeItem('metavault_token');setUser(null)}
  return <div className="app-shell"><aside className={`sidebar ${mobile?'mobile-open':''}`}><div className="brand"><div className="brand-mark"><Database size={21}/></div><b>Meta<span>Vault</span></b><button className="sidebar-close" onClick={()=>setMobile(false)}><X/></button></div><nav>{groups.map(group=><div className="nav-group" key={group}><p>{group}</p>{visible.filter(n=>n.group===group).map(item=><button className={page===item.id?'active':''} onClick={()=>select(item.id)} key={item.id}><item.icon size={18}/>{item.label}</button>)}</div>)}</nav><div className="sidebar-foot"><div className="user-mini"><span>{user.name.slice(0,1)}</span><div><b>{user.name}</b><small>{user.roles[0]||'사용자'}</small></div><button onClick={logout} title="로그아웃"><LogOut size={16}/></button></div></div></aside>{mobile&&<div className="mobile-overlay" onClick={()=>setMobile(false)}/>}<main className="workspace"><div className="topbar"><button className="mobile-menu" onClick={()=>setMobile(true)}><MenuIcon/></button><div className="system-state"><i/>시스템 정상</div><div className="top-user"><span>{user.name.slice(0,1)}</span>{user.name}<button className="ghost password-button" onClick={()=>setPasswordOpen(true)} title="비밀번호 변경"><KeyRound size={15}/>비밀번호 변경</button></div></div><div className="content">{page==='dashboard'&&<Dashboard go={select}/>} {page==='sources'&&<Sources toast={setToast}/>} {page==='jobs'&&<Jobs toast={setToast}/>} {page==='metadata'&&<Metadata/>} {page==='users'&&<UsersPage toast={setToast}/>} {page==='roles'&&<RolesPage toast={setToast}/>}</div></main>{toast&&<Toast message={toast} onClose={()=>setToast('')}/>} {passwordOpen&&<PasswordChange onClose={()=>setPasswordOpen(false)}/>}</div>
}
