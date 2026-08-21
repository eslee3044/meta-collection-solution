# MetaVault

데이터베이스 접속정보 관리, 스키마 메타데이터 수집, 수집 스케줄, 사용자·역할·권한·메뉴 관리를 제공하는 MVP입니다.

## 포함 기능

- PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, SQLite 연결 모델
- DB 비밀번호 인증 및 SSH 비밀번호/PEM 개인키 터널
- 접속 비밀번호와 SSH 키의 Fernet 암호화 저장
- 스키마, 테이블, 뷰, 컬럼, PK/FK, 인덱스, 유니크 제약 수집
- Cron, 주기, 수동 실행 스케줄과 실행 이력
- 사용자, 역할, 세부 기능 권한, 역할별 메뉴 노출
- 반응형 관리자 웹 UI

## 로컬 실행

요구사항은 Python 3.11+와 Node.js 20+입니다.

```powershell
Copy-Item .env.example .env
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

새 터미널에서:

```powershell
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173`을 열고 기본 계정 `admin@example.com` / `Admin123!`로 로그인합니다. 운영 환경에서는 `.env`의 관리자 비밀번호와 비밀키를 반드시 변경하세요.

Docker가 설치되어 있다면 저장소 루트에서 `docker compose up --build` 후 `http://localhost:8080`으로 접속할 수 있습니다. Docker 이미지에는 SQL Server용 Microsoft ODBC Driver 18과 Oracle용 `python-oracledb` Thin 모드 드라이버가 포함됩니다.

## DB 드라이버 참고

- PostgreSQL과 MySQL/MariaDB 드라이버는 기본 설치됩니다.
- SQL Server는 `pip install -e ".[mssql]"` 및 Microsoft ODBC Driver 18 설치가 필요합니다. Docker 이미지에는 자동으로 포함됩니다.
- Oracle은 `pip install -e ".[oracle]"`로 thin 드라이버를 추가합니다. Docker에서는 Oracle Client 없이 Thin 모드로 동작합니다.

## 검증

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
```

API 문서는 백엔드 실행 후 `http://localhost:8000/docs`에서 확인할 수 있습니다.

## 외부 시스템 연계

MetaVault는 외부 시스템 연계를 위해 두 가지 읽기 전용 방식을 제공합니다.

### 1. 연계 전용 REST API

기본적으로 기존 관리자 토큰을 사용할 수 있으며, 운영 환경에서는 `.env`에 `METAVAULT_INTEGRATION_API_KEY`를 설정해 `X-API-Key` 방식으로 분리하는 것을 권장합니다. API 키 값 자체는 로그나 저장소에 기록하지 않습니다.

```text
GET /api/integration/v1/sources
GET /api/integration/v1/sources/{source_id}/snapshots?limit=100
GET /api/integration/v1/sources/{source_id}/latest
GET /api/integration/v1/snapshots/{snapshot_id}
GET /api/integration/v1/snapshots/{snapshot_id}/objects?schema_name=public&kind=table
GET /api/integration/v1/sources/{source_id}/diff?from_snapshot_id=1&to_snapshot_id=2
```

`diff` 응답은 `added`, `removed`, `changed`로 구성되며 테이블·컬럼·인덱스·뷰·프로시저 변경을 포함합니다. API는 내부 DB 비밀번호나 암호화된 접속정보를 반환하지 않습니다.

### 2. PostgreSQL 읽기 전용 뷰

PostgreSQL 기동 시 다음 뷰가 `integration` 스키마에 자동 생성됩니다.

```text
integration.latest_snapshots
integration.snapshot_history
integration.schema_history
integration.table_history
integration.column_history
```

외부 계정에는 운영 테이블 전체 권한을 주지 말고 필요한 뷰에만 권한을 부여합니다.

```sql
CREATE USER metavault_reader WITH PASSWORD '[REDACTED]';
GRANT USAGE ON SCHEMA integration TO metavault_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA integration TO metavault_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA integration
  GRANT SELECT ON TABLES TO metavault_reader;
```

운영 환경에서는 PostgreSQL 포트를 인터넷에 직접 공개하기보다 내부 네트워크, VPN 또는 읽기 전용 replica를 사용하는 것을 권장합니다.
