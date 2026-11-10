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
  ├─ full_load_table       # dag_run.conf → MetaVault API
  └─ finish
```

Full Load 실행 시 `dag_run.conf`에 다음 Manifest를 전달한다.

```json
{"job_id": 1, "schema_name": "APP", "table_name": "ORDERS", "key_columns": ["ORDER_ID"]}
```

Airflow Task는 MetaVault API의 `/api/load/full`을 호출하고, API가 기존 `DataSource/source_engine`으로 원천 DB를 읽어 ST Parquet를 생성한다. 이후 다음 DQ를 실행한다.

```text
source_count == staging_count
NULL key count == 0
duplicate key row count == 0
```

DQ를 통과한 경우에만 DuckDB L0 `MERGE`를 수행한다. 실패한 ST 파일은 `datalake/quarantine/`에 복사하고 L0에는 반영하지 않는다. 결과와 DQ 수치는 `CollectionRun`과 `RunLog`에 기록한다. SQLite fixture로 API 직접 실행과 Airflow E2E 실행, DQ 성공·실패 경로를 확인했다.

현재는 Full Load 1개 테이블 수직 슬라이스다. 다음 확장 대상은 Incremental watermark, 다중 테이블 Manifest, 상세 DQ, Load Run 전용 모델, MetaVault callback/알림이다.

## 외부 Datalake 조회 API

Datalake 파일 경로를 외부에 직접 공유하지 않고, MetaVault JWT 인증이 필요한 읽기 전용 API를 사용한다.

```text
GET http://<맥미니-IP>:8000/api/datalake/tables
GET http://<맥미니-IP>:8000/api/datalake/tables/{schema}/{table}/preview?limit=100
```

예시:

```bash
BASE_URL=http://192.168.0.20:8000
TOKEN=$(curl -fsS -X POST "$BASE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$METAVAULT_ADMIN_EMAIL\",\"password\":\"$METAVAULT_ADMIN_PASSWORD\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -fsS "$BASE_URL/api/datalake/tables" \
  -H "Authorization: Bearer $TOKEN"

curl -fsS "$BASE_URL/api/datalake/tables/main/orders/preview?limit=100" \
  -H "Authorization: Bearer $TOKEN"
```

조회 권한은 `jobs:read`가 필요하고 preview limit은 1~1000행으로 제한된다. 현재 L0 DuckDB가 없으면 테이블 목록은 빈 배열을 반환한다.

현재 Compose는 API의 `8000` 포트를 LAN에 공개한다. 인터넷에 직접 포트포워딩하지 말고 Tailscale/VPN 또는 HTTPS reverse proxy 뒤에서 사용한다. 브라우저에서 다른 도메인으로 호출할 경우 `METAVAULT_CORS_ORIGINS`에 해당 HTTPS origin을 명시한다.

## 멀티엔진 Datalake 구성

현재 구현은 환경 변수로 Data Plane 모드를 선택한다.

```text
duckdb_only       ST Parquet → DQ → DuckDB L0

dual              ST Parquet → DQ → DuckDB L0 + PostgreSQL L0

postgres_serving  ST Parquet → DQ → PostgreSQL L0/serving
```

기본값은 기존 호환성을 위해 `duckdb_only`다.

```yaml
METAVAULT_DATALAKE_MODE=duckdb_only
```

PostgreSQL 모드를 사용할 때는 Data Plane PostgreSQL 연결을 별도로 지정한다. 연결 문자열 또는 host/port/name/user/password 묶음 중 하나를 사용한다. 비밀번호는 Git에 커밋하지 않고 `.env`에만 둔다.

```yaml
METAVAULT_DATALAKE_MODE=dual
METAVAULT_DATALAKE_POSTGRES_HOST=datalake-postgres
METAVAULT_DATALAKE_POSTGRES_PORT=5432
METAVAULT_DATALAKE_POSTGRES_NAME=metavault_data
METAVAULT_DATALAKE_POSTGRES_USER=metavault_dp
METAVAULT_DATALAKE_POSTGRES_PASSWORD=[REDACTED]
```

Full Load의 공통 흐름은 다음과 같다.

```text
원천 DB
  → ST Parquet
  → DQ
  ├─ 실패: quarantine Parquet, L0 미반영
  └─ 성공:
       ├─ DuckDBAdapter
       └─ PostgreSQLAdapter
```

두 엔진은 같은 ST Parquet를 읽으며 원천 DB를 두 번 조회하지 않는다. PostgreSQL adapter는 대상 schema/table을 만들고 PK 기반 `ON CONFLICT DO UPDATE`로 멱등 publish한다. 신규 컬럼은 PostgreSQL 테이블에 추가된다.

PostgreSQL Data Plane을 별도 컨테이너로 운영하려면 별도 Compose override를 사용한다. 이 서비스는 기존 `metavault-postgres-data` volume을 사용하지 않아 Control Plane 데이터를 건드리지 않는다.

```text
Control Plane PostgreSQL
  └─ metavault-postgres-data

Data Plane PostgreSQL
  └─ metavault-datalake-postgres-data
```

현재 PostgreSQL adapter는 백엔드 코드와 환경 설정을 제공하며, 기본 Compose는 기존 운영 호환성을 위해 DuckDB 모드로 유지한다. 운영 전환 전에는 `dual` 모드로 row count, PK, DQ 결과, 재실행 결과를 대조한 뒤 `postgres_serving`을 선택한다.

DBeaver에서는 Data Plane PostgreSQL에 다음처럼 접속한다. 비밀번호는 맥미니의 `.env`에서 확인하며 채팅이나 Git에는 기록하지 않는다.

```text
Host: 100.107.26.73
Port: 5434
Database: metavault_data
Username: metavault_dp
SSL: off (Tailscale 내부망에서만 접근)
```

호스트의 Tailscale IP가 바뀌면 `.env`의 `METAVAULT_DATALAKE_DB_BIND_IP`를 현재 Tailscale IP로 변경하고 Data Plane PostgreSQL 컨테이너만 재생성한다. 사내 LAN에서도 접근해야 하는 경우에만 이 값을 `0.0.0.0`으로 명시한다.
