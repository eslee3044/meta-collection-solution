# 데이터 운영 현황 — 메타 수집·Airflow 적재 통합 대시보드 구현 계획

> **For Luna:** 이 문서를 개발 명세로 사용한다. 코드 변경 전 현재 작업 트리와 기존 구현을 다시 확인하고, 아래 범위만 작업한다. 테스트를 먼저 추가하고(red 확인 후 구현), 프런트엔드·백엔드·Docker 검증을 모두 수행한다. Airflow 적재 실행, DAG 배포, DB DDL은 대시보드에서 자동 수행하지 않는다.

**목표:** `대시보드 > 데이터 운영 현황`에서 메타 수집과 Datalake/Airflow 적재 상태를 각각 구분해 요약하고, 문제 항목을 기존 관리 화면으로 안내한다.

**아키텍처:** 현재 `/api/dashboard` 메타 요약에 권한이 보장된 Datalake/Airflow 요약 데이터를 추가하되, DAG별 상세 실행·task 조회 API를 대시보드에서 그대로 반복 호출하지 않는다. 기존 `적재 스케줄·처리상태` 페이지는 상세 조회용으로 유지하고, 대시보드는 운영 KPI·경보·최근 활동만 보여준다. Airflow 미사용·장애·미설정 상태를 0건 또는 성공으로 오인하지 않도록 명시적인 가용성 상태를 전달한다.

**기술 스택:** React + TypeScript, Vite, FastAPI, SQLAlchemy, 기존 MetaVault 디자인 시스템, Docker Compose.

---

## 1. 현재 구현 기준

### 대시보드 (`frontend/src/App.tsx`, `frontend/src/dashboard.css`)

- 대시보드 컴포넌트는 `App.tsx`의 `Dashboard`다.
- 현재 `/api/dashboard`에서 데이터 소스 수, 활성 메타 수집 작업, 누적 수집 객체, 실패한 수집 실행, 메타 구조 변경 대기 건수, 최근 수집 실행을 받는다.
- 현 화면은 메타 구조 변경 알림, 4개 메타 지표 카드, 30일 수집 추이, 6단계 메타 처리 흐름으로 구성된다.
- 현재 흐름의 일부 `done` 값은 최근 실행 기록 존재 또는 누적 객체 존재만으로 완료 처리한다. 이 기준은 최근 실행 실패나 stale 누적값을 성공처럼 보이게 할 수 있으므로 상태 개선 범위에 포함한다.

### 기존 Airflow 상세 페이지

- `frontend/src/DatalakeScheduleStatusPage.tsx` 및 `GET /api/datalake-load/schedule-status`가 이미 존재한다.
- 상세 페이지는 관리 DAG, 배포 완료, 실행 중·대기, DAG별 최신 실패 수를 계산하고 DAG별 최근 실행 및 task를 제공한다.
- 페이지는 15초마다 새로고침하며, API는 각 DAG마다 Airflow DAG·실행·task 정보를 요청한다.
- `MANIFEST_ONLY`에서는 Airflow 직접 운영이 아님을 안내한다.
- 이 상세 페이지의 15초 polling을 대시보드에 복제하지 않는다. 대시보드는 별도 집계로 가볍게 갱신한다.

### 현재 변경 상태 참고

이 문서는 설계·개발 지침이며, 다른 개발 작업 중인 파일을 되돌리거나 재정렬하지 않는다. 개발자는 시작 전에 `git status --short`와 관련 파일 diff를 확인하고 문서에 기록한 파일 외의 기존 수정사항을 보존한다.

---

## 2. 화면 설계

### 화면 구조와 우선순위

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 데이터 운영 현황                 [운영 모드 배지] [새로고침] [DB 추가] │
│ 메타 수집부터 Datalake 적재까지의 운영 상태를 확인합니다.             │
├──────────────────────────────────────────────────────────────────────┤
│ [메타 구조 변경 3건 · 검토하기] [Airflow 실패 1건 · 실행 상태 보기]    │
├──────────────────────────────────────────────────────────────────────┤
│ 메타 수집                                                             │
│ [DB 연결 5] [활성 수집 스케줄 4] [수집 객체 1,240] [실패 실행 2]       │
├──────────────────────────────────────────────────────────────────────┤
│ Datalake 적재 · Airflow                                               │
│ [적재 계획 12] [DAG 배포 18/20] [실행 중·대기 2] [최신 실패 DAG 1]     │
├──────────────────────────────────────────────────────────────────────┤
│ 데이터 처리 흐름                                                      │
│ 메타: DB 연결 → Snapshot 수집 → 구조 검토 → 승인·반영                 │
│ 적재: 계획 준비 → INIT DAG 배포 → 초기 적재 → 증분 스케줄 활성화       │
├──────────────────────────────────────────────────────────────────────┤
│ 최근 운영 활동                                  [적재 상태 전체 보기]  │
│ 시각 | 대상 | 작업 유형 | 결과 | 다음 행동                            │
│ ...                                                                  │
├──────────────────────────────────────────────────────────────────────┤
│ 최근 30일 메타 수집 추이                                              │
└──────────────────────────────────────────────────────────────────────┘
```

수치는 설명을 위한 예시이며 실제 데이터로 대체한다.

### 2.1 헤더 및 운영 모드

- 기존 페이지 제목 `데이터 운영 현황`과 `DB 연결 추가` 액션을 유지한다.
- 헤더에 현재 적재 운영 모드를 짧게 표시한다.
  - `AIRFLOW_MANAGED`: `Airflow 직접 운영`
  - `MANIFEST_ONLY`: `Manifest 수동 운영`
- 시간대도 있으면 모드 배지의 보조 텍스트로 노출한다. 운영 모드/시간대 조회 실패는 전체 대시보드 렌더링을 막지 않는다.
- 사용자가 눌러 실행하는 적재·배포 액션은 넣지 않는다. 새로고침, 상세 화면 이동만 제공한다.

### 2.2 주의 알림

메타와 적재 알림을 각각 독립된 항목으로 표시한다. 한쪽에 문제가 없다고 다른 쪽의 경고를 숨기지 않는다.

- 메타: 구조 변경 승인/검토/반영 대기 건수. 기존 `변경 검토` 버튼 동작을 보존한다.
- 적재: 최신 DAG 실행 실패, 미배포 DAG 등 사용자가 조치할 대상이 있을 때만 표시한다.
- 알림이 없으면 간결한 중립 상태 한 줄만 표시하거나 알림 영역을 접는다. 큰 초록색 성공 배너로 화면을 차지하지 않는다.
- 경고 클릭은 원인을 더 볼 수 있는 기존 페이지로 이동한다.

### 2.3 KPI — 두 업무 영역을 시각적으로 분리

현재 메타 KPI는 유지하고, 그 아래에 `Datalake 적재 · Airflow` KPI 묶음을 추가한다. 데스크톱은 영역별 4열, 중간 화면은 2열, 모바일은 1열 또는 2열로 축소한다.

**메타 수집**

1. `등록 데이터 소스`
2. `활성 수집 작업`
3. `누적 수집 객체`
4. `실패한 수집 실행`

기존 카드 링크와 설명 툴팁을 보존한다. 실패 건수는 API가 실제로 세는 범위를 화면 설명/툴팁에 명시한다. 현재 `/api/dashboard` 값은 전체 실패 실행의 누적 count이므로, 기간 필터를 새로 추가하지 않는 한 `최근 실패`라는 라벨로 바꾸지 않는다.

**Datalake 적재 · Airflow**

1. `적재 계획`
2. `DAG 배포` — `배포 완료 / 전체 DAG` 형식
3. `실행 중·대기` — 최신 run state가 `running` 또는 `queued`인 DAG 수
4. `최신 실패 DAG` — DAG별 최신 run이 `failed` 또는 `upstream_failed`인 수

두 실패 지표의 집계 기준을 섞지 않는다. Airflow 지표 이름에 `DAG별 최신 실행 기준`임을 툴팁 또는 보조 문구로 밝힌다. 운영자가 기간별 총 실패 실행 수를 필요로 하면 별도 API 집계가 구현되기 전까지 해당 표현을 사용하지 않는다.

- 각 KPI는 기존 해당 관리 화면으로 이동한다.
- `DAG 배포`는 `적재 스케줄·처리상태`, `적재 계획`은 `Datalake 적재 운영`으로 연결한다.
- `MANIFEST_ONLY`일 때 Airflow run KPI를 0으로 표시하지 않는다. `Airflow 미연동` 또는 `직접 운영 모드 아님`으로 표시하고, `시스템 관리`에서 모드를 확인하는 경로를 제공한다.

### 2.4 이중 운영 흐름

기존 메타 처리 흐름을 보존하면서 Datalake 적재 흐름을 별도 lane으로 추가한다. 두 흐름을 하나의 긴 선으로 합치지 않는다. 각 노드는 현재 상태와 다음 행동을 짧게 표시하고 해당 관리 화면으로 이동한다.

**메타 수집 흐름**

`DB 연결 → Snapshot 수집 → 구조 변경 비교 → 검토·승인 → 메타 반영`

**적재 흐름**

`적재 계획 → 초기 적재 준비 → INIT DAG 배포 → 초기 적재 완료 → 증분 스케줄 활성화`

적재 상태는 기존 계획 상태를 활용한다.

- `initial_status`: 계획/진행/완료/실패를 실제 API 값에 맞게 한국어화한다.
- `incremental_status`: `LOCKED`, `READY`, `SCHEDULE_ACTIVE`를 각각 `초기 적재 전`, `증분 설정 가능`, `증분 스케줄 활성`로 안내한다.
- DAG가 없는 상태는 성공/실패가 아니라 `DAG 생성 대기` 또는 `아직 생성되지 않음`으로 표시한다.
- `MANIFEST_ONLY`에서는 Airflow 배포·run 상태를 표시할 수 없다는 점을 적재 흐름에 명시한다.

**오표시 방지 규칙**

- 최근 실행 목록에 항목이 있다는 사실만으로 Snapshot 수집을 성공 처리하지 않는다. 실제 최신 실행의 상태를 사용한다.
- 과거 누적 `objects > 0`만으로 현재 메타 반영 단계를 완료 처리하지 않는다. 현재 적용/승인 상태를 확인할 근거가 없으면 `확인 필요` 또는 중립 상태를 사용한다.
- 구조 변경 대기가 0건이면 `대기 없음`으로 표시한다. 변경이 없었다는 이유만으로 `승인 완료`를 의미하지 않는다.
- API 상태를 판정할 수 없는 경우 `성공`으로 추정하지 않는다.

### 2.5 최근 운영 활동

- 메타 수집과 Datalake 적재를 한 목록으로 보여주되, `작업 유형` 배지와 명확한 출처로 구별한다.
- 우선순위는 실패/진행 중/대기·미배포를 위에 두고, 나머지는 최근 시간순으로 정렬한다. 긴 목록을 넣지 말고 최대 5~8개를 미리 보여준다.
- 제안 컬럼: `시각`, `대상`, `작업 유형`, `상태`, `소요 시간 또는 상태 설명`, `보기`.
- 대상은 가능한 경우 시스템·인스턴스와 소유자/테이블을 함께 보여준다.
- 작업 유형은 `메타 수집`, `초기 적재`, `증분 적재` 등 사용자 업무 용어를 쓴다. 상태 배지와 작업 유형 배지를 색상·문구로 구분한다.
- 행 클릭 시 전체 상세 목록으로 이동한다. 대상별 상세 deep-link를 추가하려면 기존 라우팅 방식부터 확인하고, 구현되지 않은 선택 상태를 동작하는 것처럼 표시하지 않는다.
- Airflow trigger 버튼은 대시보드에 노출하지 않는다. 실행은 현재 적재 운영 화면에서 확인된 대상·전제조건을 본 뒤 수행하도록 한다.

### 2.6 추이 그래프

기존 `최근 30일 수집 추이`는 보존한다. 대시보드는 운영 요약이 우선이므로 KPI·알림·처리 흐름·최근 활동 뒤에 배치한다. 이 요청에서 적재 성능 추이/적재량 그래프는 추가하지 않는다(필요한 persisted metrics와 요구가 별도로 정의되지 않음).

---

## 3. 데이터/API 명세

### 권장 변경

기존 `GET /api/dashboard`의 필드와 의미를 깨지 않고, 현재 사용자에게 권한이 있는 경우 `datalake_summary`와 `orchestration` 요약을 확장한다. 또는 동등하게 권한을 검증하는 별도 `GET /api/dashboard/operations-summary`를 둔다. 어느 방식을 택하든 기존 클라이언트 호환성을 유지하고 테스트로 고정한다.

예시 응답(필드명/enum은 코드베이스의 실제 모델과 통일하고, 없는 필드를 임의로 DB 영속 상태처럼 가장하지 말 것):

```json
{
  "sources": 0,
  "active_jobs": 0,
  "objects": 0,
  "failed_runs": 0,
  "layout_changes_pending": 0,
  "recent_runs": [],
  "orchestration": {
    "mode": "AIRFLOW_MANAGED",
    "timezone": "Asia/Seoul",
    "airflow_status": "AVAILABLE",
    "checked_at": "..."
  },
  "datalake_summary": {
    "plans_total": 0,
    "dags_total": 0,
    "dags_deployed": 0,
    "latest_running_or_queued_dags": 0,
    "latest_failed_dags": 0,
    "recent_activity": []
  }
}
```

### 데이터 의미 및 안전성

- 모드와 연결 상태는 독립된 값이다. `MANIFEST_ONLY`는 Airflow 장애를 뜻하지 않고, 연결 장애는 `AIRFLOW_MANAGED`와 구분한다.
- 권장 `airflow_status`: `NOT_APPLICABLE`(Manifest 모드), `AVAILABLE`, `UNAVAILABLE`, `UNKNOWN`.
- Airflow 요청 실패 시 메타 KPI와 DB 기반 계획/DAG KPI는 계속 반환한다. Airflow 상태는 `UNAVAILABLE`과 마지막 확인 시각/짧은 설명을 주고, 전체 대시보드 요청을 500으로 실패시키지 않는다.
- DAG manifest가 없거나 plan이 없는 정상 상태는 0/빈 배열로 나타내되, UI는 의미 있는 안내문을 함께 제공한다.
- `recent_activity`의 시간대는 설정된 `timezone`에 따라 표시한다. API timestamp는 timezone-aware ISO-8601로 반환한다.
- `/api/datalake-load/schedule-status`처럼 DAG별 run/task 전체를 가져오는 경로를 dashboard 렌더마다 호출하지 않는다. 집계에 필요한 최신 run만 제한적으로 조회하거나 캐시를 사용하고, Airflow가 많은 경우 N+1 요청이 발생하지 않도록 설계한다.
- 기존 `/api/dashboard`가 `current_user`만 요구한다면 적재 데이터를 더하는 과정에서 권한을 우회하지 않는다. 최소 `jobs:read` 기준에 맞춰 요약 데이터의 노출을 제한하거나 안전한 권한 필터를 적용한다. 사용자에게 권한이 없으면 메타 섹션은 표시하되 적재 섹션은 권한 안내/미표시 처리한다.
- API 집계는 credential, Airflow 내부 URL, 오류 trace, 전체 SQL을 응답에 포함하지 않는다.

---

## 4. UI/접근성 기준

- 기존 MetaVault의 `PageHead`, `panel`, `stat-card`, `PanelHead`, 상태 배지와 한국어 typography/color token을 재사용한다. 새 전용 디자인 시스템을 만들지 않는다.
- 그룹 제목은 `메타 수집`, `Datalake 적재 · Airflow`로 분명히 한다. 지표 카드 클릭 영역과 정보 툴팁은 서로 중첩된 interactive element가 되지 않도록 구성한다.
- 오류/실패는 빨강, 진행·대기는 주의색, 성공은 초록, 사용 불가/미확인은 중립색으로 표시한다. 색상만으로 상태를 전달하지 말고 텍스트와 아이콘을 함께 쓴다.
- 카드와 흐름 노드는 키보드로 이동·실행할 수 있고, 링크/버튼에 한국어 accessible name을 둔다.
- 새로고침 중 이전 집계 수치를 무조건 0으로 초기화하지 않는다. stale 상태가 있을 때는 마지막 갱신 시각과 갱신 실패를 분리한다.
- 모바일에서 카드 overflow가 없고, 최근 활동은 가로 스크롤 또는 카드형 요약으로 읽을 수 있어야 한다. 액션 버튼 텍스트가 두 줄로 잘려 의미가 사라지지 않게 한다.

---

## 5. 개발 순서 및 파일 범위

### Task 1: API 집계 계약과 상태 의미 테스트 작성

**목표:** 메타/Datalake/Airflow 상태가 분리되고, 권한·미연동·Airflow 장애에서 안전한 응답을 보장한다.

**파일:**
- Modify: `backend/app/main.py`의 `/api/dashboard` 또는 새 집계 endpoint
- Modify/Create: `backend/tests/test_dashboard_operations_summary.py`
- 필요 시 Modify: 기존 Datalake/Airflow service 모듈(실제 구조를 확인한 뒤 최소 범위)

**검증 케이스:**
1. `MANIFEST_ONLY`: 메타 요약 유지, Airflow `NOT_APPLICABLE`, 허위 실패/성공 0 표시 없음.
2. `AIRFLOW_MANAGED` + 실행 기록 없음: DAG/계획 수는 반환되고 run 상태는 `미실행`으로 해석할 수 있음.
3. 최신 `queued`/`running`/`failed`/`upstream_failed` 집계 기준이 명세와 일치.
4. Airflow 조회 장애 시 500이 아닌 부분 응답과 `UNAVAILABLE` 반환, DB 기반 숫자는 보존.
5. 권한 없는 사용자는 적재 상세 요약을 볼 수 없음.
6. 기존 `/api/dashboard` 응답을 소비하는 기존 메타 UI/테스트의 호환성 유지.

테스트 파일과 앱 dependency fixture의 실제 이름을 먼저 검색한다. 같은 목적의 fixture가 있으면 중복 생성하지 않는다.

### Task 2: Dashboard 프런트엔드 상태 모델과 단위 테스트

**파일:**
- Modify: `frontend/src/App.tsx`의 `Dashboard`
- Create/Modify: `frontend/src/dashboardOperations.js` (집계/상태 문구를 순수 함수로 분리할 때)
- Create: `frontend/tests/dashboardOperations.test.js`

**검증:** Manifest, Airflow 정상, 장애, 데이터 없음, 권한 없음이 0/성공으로 오표시되지 않는지 테스트한다. 실제 저장소의 `package.json` 테스트 명령을 확인해 실행한다.

### Task 3: KPI·알림·최근 활동 UI 적용

**파일:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/dashboard.css`

**작업:**
1. 기존 메타 KPI 및 변경 검토 동작을 보존한다.
2. 적재 KPI 묶음을 추가하고 기존 `Datalake 적재 운영`, `적재 스케줄·처리상태` 페이지로 연결한다.
3. 적재 경고를 추가하되 메타 경고와 독립 렌더링한다.
4. 최근 활동 preview에 상태·종류·시간을 표시하고 상세 페이지 이동만 제공한다.
5. 초기 로딩/일부 API 실패/stale refresh/권한 없음/빈 데이터를 각각 구분한다.

### Task 4: 흐름도 오표시 제거 및 2-lane 전환

**파일:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/dashboard.css`
- 필요 시 Modify: `frontend/src/datalakeLoadStatus.js` 또는 공통 status helper
- Create/Modify: 흐름 상태를 검증하는 frontend test

**작업:**
- 메타 현재 상태는 실제 최신 collection run과 layout 상태에서 판정한다.
- Datalake 흐름은 plan/DAG/initial/incremental 상태를 사용한다.
- 상태를 확인할 수 없는 경우 성공 처리하지 않는다.
- 기존 메타 6단계를 무조건 삭제하지 말고 업무 흐름을 보존해 lane으로 재배치한다.

### Task 5: 회귀 검증과 실제 화면 확인

실제 `frontend/package.json`, backend test 설정, Compose 파일을 확인하고 아래의 프로젝트 명령을 사용한다. 예상 명령 예시이며 명령이 다르면 저장소 설정을 우선한다.

```bash
cd frontend
node --test tests/*.test.js
npm run build

cd ..
# 저장소에 설정된 backend 테스트 명령을 확인 후 dashboard 관련 테스트와 전체 적절한 suite 실행
# Docker Compose에서 API와 Web만 필요한 경우 해당 서비스만 build/recreate
```

- API aggregate 테스트와 프런트엔드 전체 테스트, production build가 통과해야 한다.
- 새 API를 사용하면 API와 Web 컨테이너를 필요한 서비스만 재빌드·재기동한다. DB/PostgreSQL volume은 보존하고 `down -v`를 실행하지 않는다.
- 실행 중인 서비스의 health, `/api/dashboard` 응답 상태(민감값 없이 집계 수만), Web HTTP 200과 실제 배포 bundle을 확인한다.
- 인증된 대시보드를 사용할 수 있으면 1440px 데스크톱과 모바일 viewport에서 캡처하고, 카드 정렬·경고·흐름·최근 활동·가로 overflow를 검증한다. 로그인에 막히면 비밀번호 입력/인증 우회 없이 그 사실을 명시하고 시각 검증을 완료했다고 주장하지 않는다.
- 실제 Airflow가 `AVAILABLE`이고 run이 존재하는 경우에만 최신 상태 표기를 실데이터로 검증한다. 테스트 fixture나 `queued` 결과만으로 실제 적재 성공을 주장하지 않는다.

---

## 6. 인수 기준

- [ ] 대시보드에서 메타 수집과 Datalake/Airflow 적재가 별도 그룹으로 한눈에 구별된다.
- [ ] KPI 값의 집계 기준과 실패 기준이 명확하며 기간 미정 수치를 `최근 24시간` 등으로 과장하지 않는다.
- [ ] Airflow 모드 미사용, DAG 없음, run 없음, API 장애, 권한 없음이 서로 다른 상태로 표시된다.
- [ ] Airflow 장애가 기존 메타 KPI와 추이 차트를 숨기거나 전체 대시보드를 실패시키지 않는다.
- [ ] 메타/적재 경고가 서로 독립적이며 각 알림이 적절한 관리 화면으로 연결된다.
- [ ] Snapshot/승인/메타 반영 단계는 실제 성공 상태를 근거로 하고, 과거 실행 존재/누적 객체만으로 성공을 표시하지 않는다.
- [ ] 최근 활동은 메타 수집과 초기·증분 적재를 배지/라벨로 구분하고 상세 상태 페이지로 이동한다.
- [ ] 대시보드에서는 Airflow run trigger, DAG deploy, DDL 실행을 자동·직접 수행하지 않는다.
- [ ] `MANIFEST_ONLY`에서 Airflow 상태를 0건으로 오해하게 만들지 않는다.
- [ ] 백엔드 테스트, 프런트엔드 테스트, build, 적용 대상 Docker health/bundle 검증이 통과한다.
- [ ] 인증된 화면 캡처를 못한 경우 구현 보고에서 visual acceptance 미확인을 명확히 밝힌다.

---

## 7. 범위 밖

- Datalake 적재 실행·Airflow DAG 배포·pause/unpause를 대시보드에서 직접 실행.
- 기존 적재 스케줄 상세 화면 전체를 대시보드에 복제.
- 적재량/처리시간/비용 추이 분석(요구 지표와 신뢰 가능한 저장 데이터가 별도 정의되기 전까지).
- 메타/Datalake 데이터 모델 전면 재설계.
- DB 구조 변경, DDL 적용, 테이블 drop/truncate, Airflow run trigger.
