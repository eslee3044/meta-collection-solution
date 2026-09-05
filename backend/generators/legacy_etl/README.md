# Legacy ETL generators

기존 VBA에서 호출하던 ETL 산출물 생성 Python 원본 모음입니다.

## 포함된 생성기

- BigQuery 테이블·뷰 생성
- 적재/삭제/병합 SQL 생성
- Airflow DAG 생성
- Informatica DSX·워크플로·JOB XML 생성
- 메타 Excel 연계 및 보조 XML 생성

## 현재 상태

이 디렉터리는 웹 Worker로 통합하기 전의 원본 보존 영역입니다. 각 파일의 CLI 인자와 출력 경로는 기존 VBA 호출 방식에 의존할 수 있으므로, 웹 연동 전 입력·출력 계약을 정리해야 합니다.

권장 웹 연동 순서:

1. 메타 테이블에서 생성 대상 Snapshot 생성
2. 생성 Job을 PostgreSQL에 저장
3. 별도 Worker에서 허용된 Generator를 실행
4. 생성 결과를 Job별 디렉터리에 저장
5. ZIP으로 묶어 웹에서 다운로드

## 민감정보 처리

원본에 포함되어 있던 DB 접속정보는 저장소에 평문으로 올리지 않았습니다. `write_airflow_dag.py`의 DB 접속은 다음 환경변수를 사용합니다.

```text
ETL_DB_HOST
ETL_DB_USER
ETL_DB_PASSWORD
ETL_DB_NAME
```

`iwrite_meta_v2.py`의 MySQL SQLAlchemy URL은 `ETL_MYSQL_URL` 환경변수로 지정합니다.

`.env`, 비밀번호, 토큰, 개인키, 서비스 계정 JSON은 이 디렉터리에 커밋하지 마세요.
