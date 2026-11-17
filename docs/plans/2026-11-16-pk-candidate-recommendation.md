# PK Candidate Recommendation Implementation Plan

> **For Hermes (Luna):** Use `software-development:subagent-driven-development` and `software-development:test-driven-development` to implement this plan task-by-task. Do not commit or push until the user explicitly approves.

**Goal:** Preserve source-defined primary keys and provide persisted, validated logical-PK candidates for PK-less fact tables and views using local Ollama when configured, with deterministic rule fallback.

**Architecture:** Add a dedicated candidate-history table (`TB_META_PK_CANDIDATES_EXT`) that stores one row per ordered candidate column set as JSON plus recommendation/validation/apply state. Candidate generation is metadata-only and prioritizes source constraints before local Ollama; validation runs aggregate NULL/duplicate checks against the source database without sending row data to the model. Applying a candidate updates `TB_META_COLUMNS_EXT.PK_YN` only after validation and records audit metadata.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL/internal EAPET schema, reflected external metadata databases, React/TypeScript, local Ollama, pytest, Vite, Docker Compose.

---

## Non-negotiable business rules

1. A source physical PK always wins and is copied as-is. Do not invoke AI and do not create competing candidates.
2. PK-less objects use this order: source UNIQUE constraint → source UNIQUE index → local Ollama candidates → offline rule candidates.
3. Local LLM receives schema metadata only: object name/type, columns, types, nullable, indexes, unique constraints, FKs, and view definition when available. Never send credentials or source row values.
4. A generated candidate is not a PK. It is a `LOGICAL_PK_CANDIDATE` until source-data validation passes and a user applies it.
5. `PARTITION_KEY_YN` and `UPDATE_BASE_YN` are unrelated to logical PK and must not be used as PK evidence.
6. Candidate column names must be allowlisted against the current snapshot and selected registered columns. Maximum 4 candidates, maximum 6 columns per candidate.
7. Apply is fail-closed: only `PASSED` candidates may be applied. `EMPTY_SOURCE`, `FAILED`, `UNAVAILABLE`, or `PENDING` candidates cannot be applied.
8. Applying a composite candidate sets `PK_YN='Y'` on all candidate columns and `PK_YN='N'` on all other active columns of that registered table in one transaction.
9. Internal and external metadata-storage paths must implement identical candidate generation, query, validation-state, and apply semantics.
10. Do not delete or recreate PostgreSQL/Docker volumes. Never run `docker compose down -v` or volume prune.

---

## Data model design

### New model: `MetaPkCandidate`

Create `EAPET.TB_META_PK_CANDIDATES_EXT` with one row per candidate combination.

| Column | Type | Required | Meaning |
|---|---|---:|---|
| `CANDIDATE_ID` | integer/bigint PK | yes | Surrogate key |
| `SYSTEM_CD` | varchar(32) | yes | Registered metadata key |
| `INSTANCE_NAME` | varchar(255) | yes | Registered metadata key |
| `POSTFIX` | varchar(32) | yes | Registered metadata key |
| `OWNER` | varchar(255) | yes | Source owner/schema |
| `TABLE_NAME` | varchar(255) | yes | Source object |
| `OBJECT_TYPE` | varchar(20) | yes | `TABLE` or `VIEW` |
| `SRC_DATA_SOURCE_ID` | integer | no | Source used for validation |
| `SRC_SNAPSHOT_ID` | integer | no | Snapshot used to generate candidate |
| `CANDIDATE_RANK` | integer | yes | 1–4 |
| `CANDIDATE_COLUMNS_JSON` | text | yes | Ordered JSON string array, e.g. `["ORDER_NO","LINE_NO"]` |
| `CANDIDATE_FINGERPRINT` | varchar(64) unique | yes | SHA-256 identity/dedup key |
| `SOURCE_TYPE` | varchar(40) | yes | `UNIQUE_CONSTRAINT`, `UNIQUE_INDEX`, `LOCAL_OLLAMA`, `OFFLINE_RULES`, `MANUAL` |
| `METHOD` | varchar(40) | yes | `source-unique`, `local-ollama`, `offline-rules`, `manual` |
| `MODEL_NAME` | varchar(120) | no | Ollama model when used |
| `CONFIDENCE` | numeric(5,4) or float | yes | 0–1 |
| `REASON` | text | no | Short Korean rationale |
| `STATUS` | varchar(30) | yes | `GENERATED`, `VALIDATED`, `INVALID`, `APPLIED`, `REJECTED`, `STALE` |
| `VALIDATION_STATUS` | varchar(30) | yes | `PENDING`, `PASSED`, `FAILED`, `EMPTY_SOURCE`, `UNAVAILABLE`, `NOT_REQUIRED` |
| `ROW_COUNT` | bigint | no | Validated row count |
| `NULL_COUNT` | bigint | no | Rows with NULL in any candidate column |
| `DUPLICATE_GROUP_COUNT` | bigint | no | Duplicate key groups; stop/cap if needed but record detection |
| `VALIDATED_AT` | timestamptz | no | Validation timestamp |
| `VALIDATION_MESSAGE` | text | no | Korean result/error summary; never include credentials |
| `CREATED_BY` | varchar(255) | no | Actor |
| `CREATED_AT` | timestamptz | yes | Created timestamp |
| `REVIEWED_BY` | varchar(255) | no | Reject/apply reviewer |
| `REVIEWED_AT` | timestamptz | no | Review timestamp |
| `APPLIED_BY` | varchar(255) | no | Apply actor |
| `APPLIED_AT` | timestamptz | no | Apply timestamp |

Indexes:

- Unique: `CANDIDATE_FINGERPRINT`
- Lookup: `(SYSTEM_CD, INSTANCE_NAME, POSTFIX, OWNER, TABLE_NAME, STATUS)`
- Snapshot: `(SRC_SNAPSHOT_ID)`

Fingerprint input, serialized deterministically:

```text
system_cd|instance_name|postfix|owner|table_name|snapshot_id|ordered_candidate_columns
```

Do not include model/method in the fingerprint; the same column combination is one candidate for a snapshot and may be updated with the strongest source/reason.

### Why one table instead of candidate/header + candidate-column tables

A bounded candidate has at most six ordered columns, and existing code already stores structured details in `TEXT`. A JSON text array keeps external DB DDL portable and avoids adding a second table solely for six ordered values. Every API response must parse and validate this JSON before use.

---

## API contract

All endpoints require existing `metadata:write` or `metadata:read` permission as indicated. Registered table identity is sent in the JSON/query body because the key is composite.

### 1. Generate candidates

`POST /api/metadata/registered/pk-candidates/generate` (`metadata:write`)

Request:

```json
{
  "system_cd": "ORDR",
  "instance_name": "salesdb",
  "postfix": "",
  "owner": "public",
  "table_name": "fact_order_line"
}
```

Response when source PK exists:

```json
{
  "source_pk_applied": true,
  "source_pk_columns": ["order_id"],
  "candidates": [],
  "message": "원천 PK가 있어 그대로 적용했습니다."
}
```

Response when PK is absent:

```json
{
  "source_pk_applied": false,
  "candidates": [
    {
      "candidate_id": 101,
      "rank": 1,
      "columns": ["order_no", "line_no"],
      "source_type": "LOCAL_OLLAMA",
      "method": "local-ollama",
      "confidence": 0.91,
      "reason": "주문번호와 주문 내 순번 조합으로 행을 식별할 가능성이 높습니다.",
      "status": "GENERATED",
      "validation_status": "PENDING"
    }
  ],
  "fallback_used": false
}
```

Rules:

- Resolve the registered table and its `SRC_SNAPSHOT_ID`; 404 if unavailable.
- If snapshot physical PK exists, synchronize `PK_YN` from it transactionally and return without LLM.
- Persist candidates with deterministic deduplication.
- If local AI is disabled, provider is not `ollama`, call fails, times out, or yields no valid candidates, use rules and return `fallback_used: true`.
- Existing candidate rows for an older snapshot become `STALE`.

### 2. List candidates

`GET /api/metadata/registered/pk-candidates?system_cd=...&instance_name=...&postfix=...&owner=...&table_name=...` (`metadata:read`)

Response:

```json
{
  "current_pk_columns": [],
  "current_pk_source": "NONE",
  "source_pk_columns": [],
  "items": [],
  "can_generate": true
}
```

`current_pk_source` values: `SOURCE_PK`, `LOGICAL_PK`, `NONE`.

### 3. Validate a candidate

`POST /api/metadata/registered/pk-candidates/{candidate_id}/validate` (`metadata:write`)

Response pass:

```json
{
  "candidate_id": 101,
  "validation_status": "PASSED",
  "row_count": 152340,
  "null_count": 0,
  "duplicate_group_count": 0,
  "message": "NULL과 중복이 없어 논리 PK로 적용할 수 있습니다."
}
```

Response empty source:

```json
{
  "candidate_id": 101,
  "validation_status": "EMPTY_SOURCE",
  "row_count": 0,
  "null_count": 0,
  "duplicate_group_count": 0,
  "message": "데이터가 없어 유일성을 검증할 수 없습니다."
}
```

Validation implementation:

- Re-resolve current snapshot/object and reject stale/missing columns.
- Build SQL only from inspector/snapshot-allowlisted identifiers and dialect identifier quoting.
- Never interpolate client-provided identifiers directly.
- Query row count, rows with any candidate column NULL, and whether duplicate groups exist.
- A view is validated exactly like a table, using the view result set.
- For very large sources, execute duplicate existence with an inner grouped query and one-row limit; do not transfer duplicate values.
- Catch timeout/permission issues as `UNAVAILABLE`; redact credentials and connection strings.

### 4. Apply candidate

`POST /api/metadata/registered/pk-candidates/{candidate_id}/apply` (`metadata:write`)

Request:

```json
{
  "confirm": true
}
```

Rules:

- Require `confirm=true` and `validation_status=PASSED`.
- Fail 409 if candidate snapshot differs from current registered snapshot or any candidate column is missing/inactive.
- In one transaction, set all active registered columns to `PK_YN='N'`, then candidate columns to `PK_YN='Y'`.
- Set selected candidate to `APPLIED`, other active candidates for the table to `REJECTED`, and audit fields.
- Return applied ordered columns.

### 5. Reject candidate

`POST /api/metadata/registered/pk-candidates/{candidate_id}/reject` (`metadata:write`)

Request:

```json
{
  "reason": "업무 Grain과 맞지 않음"
}
```

Only changes review status/audit; never changes `PK_YN`.

---

## Recommendation engine design

Create `backend/app/pk_recommendation.py` instead of extending `ai_description.py` further.

Public functions:

```python
def source_pk_columns(table: dict) -> list[str]: ...
def deterministic_pk_candidates(table: dict) -> list[dict]: ...
def ollama_pk_candidates(table: dict, model: str, base_url: str) -> list[dict]: ...
def recommend_pk_candidates(table: dict, provider: str, model: str) -> dict: ...
def validate_candidate_columns(table: dict, candidates: list[dict]) -> list[dict]: ...
```

Deterministic ranking:

1. UNIQUE constraint whose columns are all NOT NULL.
2. UNIQUE index whose columns are all NOT NULL.
3. Single NOT NULL columns ending `_ID`, `_NO`, `_KEY`, `_CODE`, `ID`, `NO`.
4. Composite fact grain: transaction/order/document number + line/sequence.
5. Composite aggregate grain: date + dimension IDs/codes, maximum 6 columns.
6. Return no candidate rather than inventing a weak combination.

LLM prompt requirements:

- Explain TABLE vs VIEW and fact-grain semantics.
- Return JSON only with `candidates`, each containing `columns`, `confidence`, `reason`.
- Maximum four candidates and six columns each.
- Explicitly say that amounts, quantities, descriptions, free text, audit-update timestamps, and nullable measures should not normally identify a row.
- Input includes view definition only after truncating to a safe bounded length; no secrets.

Post-processing:

- Keep only exact real column names.
- Deduplicate ordered/normalized combinations.
- Drop nullable-only weak candidates unless sourced from an actual UNIQUE constraint/index.
- Prefer UNIQUE source candidates over LLM rank.
- Confidence cannot exceed 0.75 for unvalidated LLM/rule candidates; source UNIQUE may be 0.95.

---

## UI design

### Placement

Modify registered metadata detail in `frontend/src/App.tsx`. Add a separate `PK 설정` card above the column table or beside the existing flag summary. Do not hide this in the description-generation card.

### Initial states

**Source PK exists**

```text
PK 설정                         [원천 PK]
order_id
원천 데이터베이스의 PK가 그대로 적용되었습니다.
```

No candidate button is needed unless source PK disappears in a newer snapshot.

**No PK**

```text
PK 설정                         [PK 후보 찾기]
현재 지정된 PK가 없습니다.
팩트 테이블·뷰의 논리 PK 후보를 추천하고 원천 데이터에서 검증할 수 있습니다.
```

### Candidate panel/modal

Header:

```text
논리 PK 후보 · public.fact_order_line
원천 PK가 없어 구조 기반 후보를 표시합니다. 적용 전 NULL·중복 검증이 필요합니다.
```

Candidate card:

```text
1순위  [로컬 Ollama]  신뢰도 75%
ORDER_NO + LINE_NO
주문번호와 주문 내 순번으로 행을 구분할 가능성이 높습니다.

검증: 대기
[원천 데이터 검증]
```

After pass:

```text
검증 통과
전체 152,340건 · NULL 0건 · 중복 그룹 0건
[논리 PK로 적용]
```

After fail:

```text
검증 실패
NULL 12건 · 중복 그룹 존재
[적용 불가]
```

Empty source:

```text
데이터 없음
유일성을 확인할 수 없어 적용할 수 없습니다.
```

### Interaction rules

- Generate button shows `PK 후보 분석 중…`.
- Validate button shows `NULL·중복 검증 중…`.
- Apply opens a confirmation dialog listing exact columns and explaining this is a logical PK, not a source constraint.
- Refresh registered metadata and candidate list after apply.
- Only one candidate may be applied per table.
- Show a `규칙 기반` badge when Ollama is disabled/fails; do not pretend it was AI-generated.
- Existing source PK columns remain editable only through the existing metadata edit flow; candidate apply must not override physical source PK.
- Add responsive styles in `frontend/src/registered-metadata.css`.

### Registration modal

In `ColumnSelectionModal`, keep physical source-PK badges. For a PK-less object, show only this neutral notice:

```text
원천 PK 없음 · 등록 후 논리 PK 후보를 검증할 수 있습니다.
```

Do not run source-data validation inside the registration modal; registration identity and audit target must exist first.

---

## Implementation tasks

### Task 1: Add candidate model and schema creation

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py` lifespan/bootstrap
- Modify: `backend/app/main.py::_meta_table_script`
- Modify: `backend/app/main.py::_metadata_expected_structure`
- Modify: `backend/app/main.py::_metadata_actual_structure` if index comparison needs extension
- Test: `backend/tests/test_metadata_structure_recreation.py`

**Steps:**

1. Write failing model/table-name/index tests.
2. Add `MetaPkCandidate` model with the fields above.
3. Add PostgreSQL internal table creation via SQLAlchemy metadata and required indexes.
4. Add portable external DDL to `_meta_table_script` for PostgreSQL/Oracle/MSSQL where currently supported.
5. Include `TB_META_PK_CANDIDATES_EXT` in structure check/recreation lists.
6. Run:

```bash
cd backend
python3 -m compileall -q app
.venv/bin/pytest -q tests/test_metadata_structure_recreation.py
```

Expected: PASS.

Do not commit without explicit user approval.

### Task 2: Add API schemas and candidate serialization

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/pk_recommendation.py`
- Create: `backend/tests/test_pk_recommendation.py`

**Steps:**

1. Add strict Pydantic request/response models; reject extra fields.
2. Add JSON column parsing helper that requires a non-empty list of unique strings, max six.
3. Add fingerprint helper and deduplication tests.
4. Add tests that reject fabricated LLM columns and more than six columns.
5. Run focused tests and verify failure before implementation, then pass.

### Task 3: Implement deterministic recommendation

**Files:**
- Modify: `backend/app/pk_recommendation.py`
- Test: `backend/tests/test_pk_recommendation.py`

Test cases:

- Source PK returns direct source result and no candidates.
- NOT NULL UNIQUE constraint ranks first.
- NOT NULL UNIQUE index ranks before naming rules.
- `ORDER_NO + LINE_NO` is suggested for a fact table without PK.
- Amount/quantity/comment columns are not suggested as identifiers.
- No plausible key returns an empty candidate list.
- Composite candidates preserve column order and max-six limit.

### Task 4: Implement local Ollama recommendation with fallback

**Files:**
- Modify: `backend/app/pk_recommendation.py`
- Test: `backend/tests/test_pk_recommendation.py`

**Steps:**

1. Reuse the local-host allowlist and `METAVAULT_LOCAL_AI_URL` safety policy from `ai_description.py`; ideally extract shared Ollama transport to avoid duplication.
2. Reuse current `MetaTableConfig.description_ai_enabled/provider/model` as the initial local-AI source of truth; do not add duplicate credentials/settings.
3. Add mocked Ollama success, invalid-column, malformed JSON, timeout, and disabled-provider tests.
4. Confirm all failure paths return deterministic rules with `method=offline-rules`.
5. Do not send row values or credentials.

### Task 5: Add candidate persistence service

**Files:**
- Create: `backend/app/pk_candidate_service.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_pk_candidate_api.py`

**Steps:**

1. Resolve registered table identity for internal and reflected external metadata storage.
2. Resolve its current source snapshot/object.
3. Mark older-snapshot candidates `STALE`.
4. Upsert/deduplicate current candidates by fingerprint.
5. Add generate and list endpoints with permissions.
6. Add route-registration introspection test.
7. Verify source PK path does not call Ollama.

### Task 6: Add source-data validation

**Files:**
- Create: `backend/app/pk_validation.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_pk_validation.py`

**Steps:**

1. Resolve source `DataSource` through candidate/table metadata.
2. Allowlist schema/table/column identifiers against current snapshot.
3. Quote identifiers with SQLAlchemy dialect preparer.
4. Add row-count, NULL-count, and duplicate-existence/count queries.
5. Support table and view objects.
6. Add tests for PASS, NULL failure, duplicate failure, empty source, stale candidate, missing column, permission error, and redaction.
7. Ensure query results contain counts only, never source values.

### Task 7: Add transactional apply/reject

**Files:**
- Modify: `backend/app/pk_candidate_service.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_pk_candidate_api.py`

**Steps:**

1. Write fail-closed tests: pending/failed/empty/stale cannot apply.
2. Implement internal apply transaction.
3. Implement reflected external apply transaction with identical semantics.
4. Set selected columns `PK_YN='Y'`, all other active table columns `N`.
5. Audit candidate and reject competing active candidates.
6. Add idempotency test: applying already-applied same candidate returns current success without corruption.
7. Add reject test proving `PK_YN` is unchanged.

### Task 8: Add frontend API functions/state

**Files:**
- Modify: `frontend/src/api.ts` if typed wrappers live there; otherwise keep existing `api()` convention in `App.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`

**Steps:**

1. Add `PkCandidate`, validation response, and table identity types.
2. Add load/generate/validate/apply/reject state.
3. Preserve current selected table on reload.
4. Show exact Korean backend errors.
5. Do not couple this state to description suggestions or PARTITION/UPDATE recommendations.

### Task 9: Implement PK settings UI

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/registered-metadata.css`

**Steps:**

1. Add physical-PK state card.
2. Add no-PK callout and candidate-generation button.
3. Add candidate cards/modal with badges, ordered column chips, reason, confidence, and validation counters.
4. Disable apply unless validation passed.
5. Add confirmation dialog for logical-PK application.
6. Add loading/empty/failure/stale states.
7. Add registration-modal notice for PK-less objects.
8. Verify responsive layout and keyboard focus.

### Task 10: Regression and Docker verification

Run:

```bash
cd /Users/eslee/meta-collection-solution/backend
python3 -m compileall -q app
.venv/bin/pytest -q

cd /Users/eslee/meta-collection-solution/frontend
npm run build

cd /Users/eslee/meta-collection-solution
git diff --check
docker compose build api web
docker compose up -d --no-deps --force-recreate api web
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8090/
```

Expected:

- All backend tests pass.
- Frontend build succeeds.
- `git diff --check` succeeds.
- API health is `{"status":"ok","service":"MetaVault"}`.
- Web returns HTTP 200.
- Docker volumes remain intact.

Perform authenticated browser acceptance:

1. Open a registered table with a physical source PK; verify source badge and no candidate override.
2. Open a PK-less fact table; generate candidates.
3. Verify local Ollama badge when configured.
4. Disable/unavailable Ollama; verify `규칙 기반` fallback.
5. Validate a known unique candidate; verify counts and enabled apply.
6. Validate a duplicate candidate; verify disabled apply.
7. Apply a passed composite candidate; reload and confirm exact `PK_YN` columns.
8. Open a PK-less view and verify candidate + source result-set validation.
9. Confirm internal and external metadata-storage modes behave identically.

---

## Security and operational checklist

- [ ] No source row values are sent to Ollama.
- [ ] No credentials, URLs with passwords, or connection strings are logged.
- [ ] Candidate identifiers are allowlisted and dialect-quoted.
- [ ] Apply is transactional and fail-closed.
- [ ] Physical source PK cannot be overwritten by AI candidate apply.
- [ ] External and internal storage paths share behavior.
- [ ] Old snapshot candidates become stale.
- [ ] PostgreSQL volume is preserved.
- [ ] No commit/push without explicit approval.

## Explicitly out of scope for this iteration

- Creating a physical PK constraint on the source database.
- Sending sample rows to any LLM.
- Automatically applying an unvalidated candidate.
- Background periodic revalidation.
- Parsing every SQL dialect's view definition into a full relational lineage graph.
- Surrogate-key generation in the source system.
