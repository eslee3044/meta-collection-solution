"""Metadata-only logical primary-key recommendation functions."""
from __future__ import annotations
import hashlib, json, logging, os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .ai_description import _ALLOWED_LOCAL_HOSTS
logger = logging.getLogger(__name__)
MAX_CANDIDATES, MAX_COLUMNS = 4, 6
_WEAK = ("AMOUNT", "AMT", "QTY", "QUANTITY", "PRICE", "COST", "FEE", "COMMENT", "COMMENTS", "DESC", "DESCRIPTION", "TEXT", "NOTE", "MEMO")
_AUDIT = ("CREATED", "CREATE", "UPDATED", "UPDATE", "MODIFIED", "MODIFY", "DELETED", "DELETE", "TIMESTAMP", "DTTM")

def _name(c): return str(c.get("column_name", c.get("name", ""))).strip()
def _columns(t): return [c for c in t.get("columns", []) if _name(c)]
def _not_null(c): return c.get("nullable") is False or str(c.get("null_yn", "")).upper() == "N"
def _uc(i):
    if isinstance(i, (list, tuple)):
        values = i
    elif isinstance(i, dict):
        values = i.get("columns") or i.get("column_names") or i.get("constrained_columns") or []
    else:
        values = []
    return [str(x).strip() for x in values if str(x).strip()]
def source_pk_columns(table): return _uc(table.get("primary_key") or table.get("pk") or {})
def _candidate(columns, source_type, method, confidence, reason):
    return {"columns": columns[:MAX_COLUMNS], "source_type": source_type, "method": method, "confidence": min(confidence, .95 if source_type in {"UNIQUE_CONSTRAINT", "UNIQUE_INDEX"} else .75), "reason": reason}
def _weak(name, c):
    u, typ = name.upper(), str(c.get("data_type", c.get("type", ""))).upper()
    return any(x in u for x in _WEAK) or "TEXT" in typ or "CLOB" in typ or any(x in u for x in _AUDIT)

def deterministic_pk_candidates(table):
    if source_pk_columns(table): return []
    by_name = {_name(c): c for c in _columns(table)}; result = []
    for key, source_type in (("unique_constraints", "UNIQUE_CONSTRAINT"), ("unique_indexes", "UNIQUE_INDEX"), ("indexes", "UNIQUE_INDEX")):
        for item in table.get(key, []) or []:
            if key == "indexes" and not item.get("unique", False): continue
            names = _uc(item)
            if names and all(n in by_name for n in names) and all(_not_null(by_name[n]) for n in names): result.append(_candidate(names, source_type, "source-unique", .95, "원천 DB에 유일 제약조건 또는 유일 인덱스가 있고 빈 값이 허용되지 않는 컬럼 조합입니다."))
    names = [n for n,c in by_name.items() if _not_null(c) and not _weak(n,c) and (n.upper().endswith(("_ID", "_NO", "_KEY", "_CODE")) or n.upper() in {"ID", "NO"})]
    for n in sorted(names, key=lambda x: (not x.upper().endswith("_ID"), x.upper())): result.append(_candidate([n], "OFFLINE_RULES", "offline-rules", .70, "빈 값이 허용되지 않고 컬럼명이 식별자 형식이라 후보로 추천했습니다."))
    order = next((n for n in by_name if n.upper() in {"ORDER_NO","ORD_NO","ORDER_ID","DOCUMENT_NO","DOC_NO"} and _not_null(by_name[n])), None)
    line = next((n for n in by_name if n.upper() in {"LINE_NO","LINE_ID","SEQ","SEQUENCE_NO"} and _not_null(by_name[n])), None)
    if order and line: result.append(_candidate([order,line], "OFFLINE_RULES", "offline-rules", .75, "주문/문서 번호와 행 순번의 팩트 grain입니다."))
    out=[]; seen=set()
    for x in result:
        k=tuple(x["columns"])
        if k not in seen and len(k)<=MAX_COLUMNS: seen.add(k); out.append(x)
    return out[:MAX_CANDIDATES]

def validate_candidate_columns(table, candidates):
    valid={_name(c) for c in _columns(table)}; out=[]; seen=set()
    for item in candidates:
        cols=item.get("columns") if isinstance(item,dict) else item
        if not isinstance(cols,list) or not 1<=len(cols)<=MAX_COLUMNS or any(not isinstance(c,str) or c not in valid for c in cols): continue
        key=tuple(cols)
        if key in seen: continue
        seen.add(key); copy=dict(item) if isinstance(item,dict) else {"columns":cols}; copy["columns"]=cols; copy["confidence"]=min(float(copy.get("confidence",.75)),.75); out.append(copy)
    return [dict(item, rank=rank) for rank, item in enumerate(out[:MAX_CANDIDATES], 1)]

def candidate_fingerprint(system_cd, instance_name, postfix, owner, table_name, snapshot_id, columns):
    raw="|".join([str(system_cd),str(instance_name),str(postfix),str(owner),str(table_name),str(snapshot_id),"|".join(columns)])
    return hashlib.sha256(raw.encode()).hexdigest()

def parse_candidate_columns(value):
    if isinstance(value, str):
        # Candidate JSON is persisted text and may be externally supplied/corrupted.
        # Bound it before parsing so reads cannot consume unbounded input.
        if len(value) > 4096:
            raise ValueError("candidate columns JSON is too large")
        parsed=json.loads(value)
    else:
        parsed=value
    if not isinstance(parsed,list) or not parsed or len(parsed)>MAX_COLUMNS or any(not isinstance(x,str) or not x.strip() for x in parsed) or len(set(parsed))!=len(parsed): raise ValueError("candidate columns must be 1-6 unique non-empty strings")
    return parsed

def ollama_pk_candidates(table, model, base_url):
    p=urlsplit(base_url)
    if p.scheme not in {"http","https"} or p.hostname not in _ALLOWED_LOCAL_HOSTS: raise ValueError("non-local Ollama URL")
    view_definition = str(table.get("view_definition") or "")[:12000]
    safe={"name":str(table.get("name",table.get("table_name",""))),"object_type":str(table.get("object_type","TABLE")),"columns":[{"name":_name(c),"data_type":str(c.get("data_type",c.get("type",""))),"nullable":c.get("nullable")} for c in _columns(table)],"unique_constraints":[_uc(x) for x in table.get("unique_constraints",[])],"unique_indexes":[_uc(x) for x in table.get("unique_indexes",[])],"indexes":[{"columns":_uc(x),"unique":bool(x.get("unique",False))} for x in table.get("indexes",[]) if isinstance(x,dict)],"foreign_keys":[_uc(x.get("constrained_columns") or x) if isinstance(x,dict) else _uc(x) for x in table.get("foreign_keys",[])],"view_definition":view_definition}
    prompt="Return JSON only with candidates containing columns, confidence, reason. Use only exact input column names; max 4 candidates and 6 columns each. Do not use amounts, quantities, descriptions, free text, audit-update timestamps, or nullable measures. Never request row values, credentials, passwords, tokens, or connection strings. Consider TABLE vs VIEW fact-grain semantics.\n"+json.dumps(safe,ensure_ascii=False)
    req=Request(f"{base_url.rstrip('/')}/api/generate",data=json.dumps({"model":model,"prompt":prompt,"stream":False,"format":"json","options":{"temperature":0}}).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urlopen(req,timeout=45) as response: body=json.loads(response.read().decode())
    payload=json.loads(body.get("response","{}"))
    if not isinstance(payload,dict) or not isinstance(payload.get("candidates"),list): raise ValueError("invalid candidate response")
    normalized=[]
    for item in payload["candidates"]:
        if isinstance(item, dict):
            normalized.append({**item, "source_type": "LOCAL_OLLAMA", "method": "local-ollama"})
    return validate_candidate_columns(table,normalized)

def recommend_pk_candidates(table, provider, model):
    source=source_pk_columns(table)
    if source: return {"source_pk_applied":True,"source_pk_columns":source,"candidates":[],"fallback_used":False,"method":"source-pk"}
    # Source uniqueness is authoritative and must beat both Ollama and naming rules.
    source_candidates = [item for item in deterministic_pk_candidates(table) if item.get("source_type") in {"UNIQUE_CONSTRAINT", "UNIQUE_INDEX"}]
    if source_candidates:
        return {"source_pk_applied":False,"source_pk_columns":[],"candidates":source_candidates,"fallback_used":False,"method":"source-unique"}
    if provider=="ollama":
        try:
            candidates=ollama_pk_candidates(table,model,os.getenv("METAVAULT_LOCAL_AI_URL","http://host.docker.internal:11434"))
            if candidates: return {"source_pk_applied":False,"source_pk_columns":[],"candidates":candidates,"fallback_used":False,"method":"local-ollama"}
        except Exception as error: logger.warning("PK Ollama recommendation failed; falling back (%s)",type(error).__name__)
    return {"source_pk_applied":False,"source_pk_columns":[],"candidates":deterministic_pk_candidates(table),"fallback_used":True,"method":"offline-rules"}
