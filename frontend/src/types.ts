export type User = { id: number; email: string; name: string; is_active: boolean; roles: string[]; permissions: string[]; menus: string[] }
export type Source = { id: number; name: string; db_type: string; host: string; port?: number; database: string; username: string; options: Record<string, unknown>; ssh_enabled: boolean; ssh_host?: string; ssh_port: number; ssh_username?: string; ssh_auth_type?: string; status: string; last_tested_at?: string; created_at: string }
export type Job = { id: number; name: string; data_source_id: number; schedule_type: string; cron: string; interval_minutes?: number; schemas: string[]; collection_items: string[]; collect_storage: boolean; is_active: boolean; next_run_at?: string; created_at: string }
export type Run = { id: number; job_id: number; status: string; current_step: string; current_schema?: string; heartbeat_at?: string; cancel_requested_at?: string; cancelled_at?: string; error_code?: string; attempt_count: number; max_attempts: number; next_attempt_at?: string; started_at: string; finished_at?: string; object_count: number; error_message?: string }
export type RunLog = { id: number; run_id: number; sequence: number; level: string; step: string; message: string; details?: string; created_at: string }
export type Role = { id: number; name: string; description: string; permissions: number[]; menus: number[] }
export type Permission = { id: number; code: string; description: string }
export type Menu = { id: number; code: string; label: string; path: string; icon: string; order: number }
export type Capabilities = { deployment_mode: string; supported_db_types: string[]; excluded_db_types: string[] }
export type WorkerStatus = { queued: number; running: number; retry_wait: number; failed: number; timeout: number; stalled: number; stale_minutes: number; poll_seconds: number }

export type RegisteredTableIdentity = { system_cd: string; instance_name: string; postfix: string; owner: string; table_name: string }
export type PkCandidate = { candidate_id: number | null; rank: number; columns: string[]; source_type: string; method: string; confidence: number; reason: string; status: string; validation_status: 'PENDING' | 'PASSED' | 'FAILED' | 'EMPTY_SOURCE' | 'UNAVAILABLE' | 'NOT_REQUIRED'; row_count?: number | null; null_count?: number | null; duplicate_group_count?: number | null; validation_message?: string }
export type PkCandidatesResponse = { source_pk_applied: boolean; source_pk_columns: string[]; candidates: PkCandidate[]; fallback_used: boolean; message: string }
export type PkCandidatesListResponse = { current_pk_columns: string[]; current_pk_source: 'SOURCE_PK' | 'LOGICAL_PK' | 'NONE'; source_pk_columns: string[]; items: PkCandidate[]; can_generate: boolean }
export type PkValidationResponse = { candidate_id: number; validation_status: PkCandidate['validation_status']; row_count?: number | null; null_count?: number | null; duplicate_group_count?: number | null; message: string }
