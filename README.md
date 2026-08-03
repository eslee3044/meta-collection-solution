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

Docker가 설치되어 있다면 저장소 루트에서 `docker compose up --build` 후 `http://localhost:8080`으로 접속할 수 있습니다. Docker 배포 모드에서는 기본 이미지에 포함되지 않은 SQL Server와 Oracle을 신규 연결·연결 테스트·수집 대상에서 제외합니다. 기존에 등록된 SQL Server/Oracle 작업도 스케줄러가 자동으로 실행하지 않습니다.

## DB 드라이버 참고

- PostgreSQL과 MySQL/MariaDB 드라이버는 기본 설치됩니다.
- SQL Server는 `pip install -e ".[mssql]"` 및 Microsoft ODBC Driver 18 설치가 필요합니다.
- Oracle은 `pip install -e ".[oracle]"`로 thin 드라이버를 추가합니다.

## 검증

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
```

API 문서는 백엔드 실행 후 `http://localhost:8000/docs`에서 확인할 수 있습니다.
