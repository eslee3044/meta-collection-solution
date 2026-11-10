# 맥미니 로컬 Datalake 개발 구성

MetaVault의 로컬 Data Plane 개발 구성이다.

```text
PostgreSQL = Control Plane
  - 데이터소스, 수집 스케줄, 실행 상태, Snapshot, Audit

DuckDB = Data Plane 엔진
Parquet = ST 배치 파일 / 향후 GCS 이식 대상
```

## 디렉터리

```text
datalake/
├── st/          # 원천에서 추출한 불변 배치 Parquet
├── l0/          # DuckDB l0.duckdb 및 관리 테이블
└── quarantine/  # DQ 실패 또는 보류 파일
```

`datalake/`는 Git에 저장하지 않으며 Docker Compose에서 API와 Worker에 다음 경로로 마운트된다.

```text
/var/lib/metavault/datalake
```

## Python API

`backend/app/datalake.py`에 현재 로컬 Data Plane primitive가 있다.

```python
from app.datalake import merge_parquet_to_l0, write_staging_parquet

staging = write_staging_parquet(
    rows,
    schema_name="sales",
    table_name="orders",
    batch_id="20261110-01",
)

result = merge_parquet_to_l0(
    staging,
    schema_name="sales",
    table_name="orders",
    key_columns=["order_id"],
)
```

지원하는 동작:

- ST Parquet 생성
- ZSTD 압축
- L0 DuckDB 영속 파일 생성
- 키 기반 `MERGE`
- 같은 배치 재실행의 멱등성
- 신규 컬럼 자동 추가
- 안전하지 않은 식별자 거부

## 운영 원칙

- PostgreSQL volume은 삭제하거나 초기화하지 않는다.
- ST 파일은 배치 완료·검증 후 보존기간을 두고 정리한다.
- L0 적재와 건수 검증 결과는 PostgreSQL Control Plane에 기록한다.
- 원천 행 데이터와 비밀정보를 API 로그에 기록하지 않는다.
- 향후 `LocalParquetStorage`를 `GCSStorage`로 교체할 수 있도록 Data Plane 경계를 유지한다.

## 현재 범위와 다음 단계

현재는 맥미니에서 실제 Parquet 생성과 DuckDB L0 MERGE를 검증할 수 있는 기반을 구성했다. 기존 스키마 수집 작업은 계속 PostgreSQL Snapshot에 저장된다.

다음 단계는 별도 기능으로 다음 흐름을 연결한다.

```text
수집된 Table 선택
  → 원천 행 추출
  → ST Parquet 저장
  → DuckDB L0 MERGE
  → 건수·중복·스키마 검증
  → PostgreSQL Load Run / Audit Log 저장
```

운영 전환 시에는 다음처럼 바꾼다.

```text
Local Parquet + DuckDB
  → GCS Parquet + BigQuery
```

## Airflow 로컬 구성

Airflow는 별도 override 파일로 구성한다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.airflow.yml \
  up -d airflow-postgres airflow-init airflow-scheduler airflow-webserver
```

구성은 다음과 같다.

```text
airflow-postgres = Airflow metadata 전용 DB
airflow-scheduler = DAG 스케줄·Task 실행 조정
LocalExecutor = 맥미니 단일 호스트 실행기
airflow-webserver = http://127.0.0.1:8085
```

MetaVault PostgreSQL volume과 Airflow metadata volume은 분리한다. Airflow metadata DB는 호스트 포트를 공개하지 않고 Docker 내부 네트워크에서만 접근한다.

현재 DAG:

```text
metavault_local_datalake
  ├─ verify_local_datalake
  ├─ extract_to_st       # 다음 단계에서 원천 Extract 연결
  ├─ run_dq_checks       # 건수·PK·DQ 연결 예정
  └─ merge_to_l0         # DuckDB L0 MERGE 연결 예정
```

검증용 DAG는 실제 trigger 후 `success` 상태를 확인했다. 현재 적재 Task는 의도적으로 skeleton이며, 원천 행 추출·DQ·L0 MERGE·MetaVault callback 연결은 다음 단계에서 구현한다.
