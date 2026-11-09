# Datalake 테이블 자동생성·자동적재 아키텍처 검토

- 작성 기준: MetaVault 현재 저장소 및 제미(Gemini) 독립 리뷰
- 대상: `/Users/eslee/meta-collection-solution`
- 상태: 설계 검토 문서

## 1. 결론

MetaVault Worker와 Airflow를 분리한다.

- **MetaVault Worker(Control Plane)**: 스키마 수집, Snapshot/Diff, 타겟 테이블 정의, DDL Plan, Type Mapping, 승인, Manifest/DAG 생성, Airflow 실행 요청, 결과 동기화
- **Airflow(Data Plane)**: 소스 Extract, Object Storage 또는 ST 적재, DQ 검증, L0 MERGE, 재시도·Backfill·SLA·결과 callback

MetaVault가 대량 데이터를 직접 Python 메모리로 옮기는 구조는 피한다. 현재 Worker는 PostgreSQL queue, DataSource 단위 동시성, heartbeat/retry/cancel을 가진 메타데이터 수집용 구조이며 대용량 다단계 적재용 orchestration 기능은 없다.

## 2. 현재 구조에서 확인된 사실

- Compose는 PostgreSQL, FastAPI API, 별도 Worker, Nginx Web 구조다.
- API가 APScheduler로 수집 실행을 queue에 넣고 Worker가 `CollectionRun`을 polling한다.
- 동일 DataSource에 대해서는 `FOR UPDATE`와 active-run 확인으로 수집을 직렬화한다.
- `SchemaSnapshot`에 수집 결과 JSON과 fingerprint를 저장하고 Snapshot Diff를 제공한다.
- Oracle, PostgreSQL, MySQL/MariaDB, MSSQL, SQLite, DB2, BigQuery, Vertica 등 여러 소스 catalog 수집이 구현되어 있다.
- `TB_META_TABLES_EXT`, `TB_META_COLUMNS_EXT` 등록 구조와 날짜·파티션 기준 추천 기능이 있다.
- `backend/generators/legacy_etl`에는 과거 VBA/CLI 기반 Airflow DAG·SQL·BigQuery 생성기가 보관되어 있으나 현재 Web Worker와 완전히 통합된 상태는 아니다.
- 현재 Compose에는 Airflow, 외부 메시지 브로커, Datalake 서비스가 포함되어 있지 않다.

BigQuery, `lnd0/ST` 및 `L0` 레이어는 기존 generator를 근거로 한 설계 가정이다. 실제 1차 타겟 제품은 구현 전에 확정해야 한다.

## 3. 권장 목표 구조

```text
Source DB
  ├─ MetaVault Worker
  │    ├─ Catalog 수집
  │    ├─ Snapshot / Diff
  │    ├─ DDL Plan / Dry-run / 승인 / 실행
  │    └─ Airflow Manifest 생성·Trigger
  └─ Airflow
       ├─ Extract
       ├─ Object Storage 또는 ST
       ├─ DQ 검증
       ├─ L0 MERGE
       └─ MetaVault callback

MetaVault PostgreSQL
  ├─ SchemaSnapshot
  ├─ MetaTable / MetaColumn
  ├─ DatalakeTarget
  ├─ DatalakeTableSpec
  ├─ DDL Plan
  ├─ Load Run
  └─ Audit Log
```

테이블마다 Python DAG를 계속 생성하기보다는 초기에는 기존 generator와 호환되는 얇은 DAG/Manifest를 사용하고, 이후 공통 DAG Factory와 동적 TaskGroup으로 전환한다.

## 4. 선결 위험

### 4.1 DBMS 종류와 실제 database 이름 혼용

`db_type`과 `database_name`의 의미를 분리한다.

```text
source_db_type
source_database_name
source_instance_name
source_schema_name
```

### 4.2 다중 스키마 동명 테이블

`ORDERS`만으로 식별하지 않고 `(schema_name, table_name)`을 사용한다.

### 4.3 부분 수집을 삭제로 오판

수집 결과에 다음 상태를 저장한다.

```text
complete / partial / failed
```

`partial` Snapshot에서는 `removed` Diff 및 자동 DDL을 차단한다.

### 4.4 재등록 시 수동 설정 유실

자동 추천과 사용자가 확정한 값을 분리한다.

```text
partition_key_suggested
partition_key_confirmed
update_base_suggested
update_base_confirmed
```

### 4.5 증분 경계 중복

증분 조건은 반개구간으로 통일한다.

```sql
WHERE update_time >= :window_start
  AND update_time <  :window_end
```

### 4.6 레거시 generator 보안·실행성

f-string SQL 및 식별자 직접 삽입을 제거하고 identifier validation/quoting을 적용한다. DAG와 SQL에는 비밀번호나 서비스 계정 키를 넣지 않고 Airflow Connection ID 또는 Secret Manager 참조만 기록한다.

### 4.7 heartbeat와 임시 인증파일

대용량 catalog 수집 중 heartbeat가 누락되지 않도록 주기적으로 갱신한다. SSH/SSL 임시파일은 `0600`, 종료 시 정리, 비정상 종료 후 재기동 시 잔류파일 정리까지 고려한다.

### 4.8 API 내장 APScheduler 중복 실행

API scale-out 시 scheduler가 중복 실행될 수 있다. scheduler leader election 또는 전용 scheduler process로 분리한다.

## 5. 권장 모델

### `datalake_targets`

타겟 종류, 접속정보, ST/L0 위치, Object Storage, Airflow endpoint와 secret reference를 저장한다.

### `datalake_table_specs`

소스/타겟 table, load mode, 증분 컬럼, 파티션 컬럼, schema evolution 정책, 적용 Snapshot, spec version, 상태를 저장한다.

### `datalake_ddl_plans`

기준 Snapshot, 변경등급, DDL 목록, fingerprint, dry-run/승인/실행 상태, 승인자와 오류를 저장한다.

### `datalake_load_runs`

init/incremental/backfill, window, Airflow DAG/run ID, 상태, source/staging/target count, PK 중복, 오류를 저장한다.

### `audit_logs`

DDL 승인·실행, pipeline 배포·trigger, metadata 변경, secret 변경을 불변 이벤트로 남긴다.

## 6. DDL 및 스키마 진화 정책

| 변경 | 정책 |
|---|---|
| 신규 nullable 컬럼 | 정책에 따라 자동 추가 |
| 문자열 길이 증가 | 대부분 안전 처리 |
| 숫자 정밀도·타입 확장 | 승인 필요 |
| NOT NULL 컬럼 추가 | 승인 필요 또는 nullable 완화 |
| 컬럼 삭제 | 물리 삭제 금지, deprecated 처리 |
| PK 변경 | 자동 반영 금지 |
| 호환 불가 타입 변경 | 새 버전 테이블 또는 전체 재적재 |
| 권한 부족/partial 수집 | 자동 변경 금지 |

실행 흐름은 다음과 같다.

```text
Plan 생성 → Dry-run → 위험등급 판정 → 승인 → 실행 → 결과·감사로그
```

DDL 실행은 현재 타겟 카탈로그와 목표 스키마를 비교하는 state reconciliation 방식으로 만들고, 동일 plan fingerprint 재실행은 no-op이어야 한다.

## 7. Airflow 파이프라인

```text
Extract
  → ST/Object Storage Load
  → Row Count·PK 중복·기본 DQ
  → L0 MERGE
  → 적재 결과 callback
```

ST는 같은 논리 실행일자와 partition을 재실행해도 중복되지 않도록 truncate 또는 partition delete 후 재적재한다. L0 MERGE는 PK 기준 중복 제거와 최신 update timestamp 보호를 적용한다.

실패 시 전체 Extract부터 다시 하지 않고 ST, DQ, MERGE 단계부터 부분 재실행할 수 있어야 한다.

## 8. 단계별 구현 순서

### Phase 0: 정합성 수정

1. DBMS/database/schema/table 식별자 정리
2. 다중 스키마 동명 테이블 수정
3. partial Snapshot 보호
4. 수동 metadata flag 보존
5. SQL identifier 검증·quoting
6. 레거시 generator 환경변수·import·PK 없는 테이블 처리

### Phase 1: Target과 Table Spec

Datalake target, ST/L0 정책, Object Storage, Airflow connection reference를 등록한다.

### Phase 2: Canonical Type Mapper

입력은 `(source_db_type, data_type, length, precision, scale, nullable)`이고 타겟 타입, nullable, 파티션 후보, 변환 경고를 출력한다.

### Phase 3: Auto-DDL Plan

Snapshot → Table Spec → target catalog 비교 → DDL Plan → Dry-run → 승인 → 실행 순서로 구현한다.

### Phase 4: Airflow Manifest 및 적재

Extract SQL, ST load, DQ, L0 MERGE, callback을 표준화한다. 처음에는 기존 generator와 호환되는 Manifest/DAG를 만들고 이후 Dynamic DAG로 전환한다.

### Phase 5: 모니터링·Backfill

실행 이력, 단계별 로그, 날짜 Backfill, source/target count, PK 중복, 실패 알림을 추가한다.

## 9. MVP 범위

처음에는 타겟 1종과 소스 1~2종만 지원한다.

```text
- ST → L0 2계층
- Full Load
- Incremental Merge
- 신규 nullable 컬럼 자동 추가
- 위험 변경 승인
- 표준 Airflow DAG
- source/staging/target count 검증
- Load Run 및 Audit Log
```

다음은 MVP에서 제외한다.

```text
- 자동 컬럼 삭제
- 자동 PK 변경
- 복수 Datalake 동시 지원
- 완전 자동 breaking migration
- 무제한 동적 DAG 생성
```

## 10. 필수 테스트

- 9종 소스 DB 타입 매핑
- Oracle DATE와 timestamp 처리
- PK 없는 테이블
- update 기준 컬럼이 없는 테이블
- 다중 스키마 동명 테이블
- partial Snapshot의 removed 보호
- 동일 DDL Plan 2회 실행
- 동일 증분 window 2회 실행
- Backfill이 최신 row를 덮어쓰지 않는지 확인
- ST 중복 방지
- worker kill/recovery
- heartbeat 유지
- source별 Airflow Pool 제한
- DDL 승인·거부·감사로그
- SQL identifier 및 comment injection 방어

## 11. 최종 권고

Airflow는 사용하는 것이 적절하다. 단, 역할은 실제 대용량 적재와 다단계 orchestration으로 제한한다. MetaVault는 metadata/control plane으로 유지하고, DDL과 pipeline specification을 안전하게 계획·승인·배포하는 시스템으로 확장하는 것이 가장 안정적이다.

실제 구현 전에는 1차 Datalake 타겟이 BigQuery인지, 또는 Iceberg/Delta/Snowflake인지 확정해야 한다. 이 결정에 따라 DDL, partition, MERGE, schema evolution 정책이 달라진다.
