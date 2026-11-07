-- MetaVault external PostgreSQL schema
-- Generated from backend/app/models.py; no passwords or application secrets are included.
BEGIN;
CREATE SCHEMA IF NOT EXISTS "EAPET";


CREATE TABLE "EAPET"."TB_META_COLUMNS_EXT" (
	system_cd VARCHAR(32) NOT NULL, 
	instance_name VARCHAR(255) NOT NULL, 
	postfix VARCHAR(32) NOT NULL, 
	owner VARCHAR(255) NOT NULL, 
	table_name VARCHAR(255) NOT NULL, 
	column_name VARCHAR(255) NOT NULL, 
	column_id INTEGER, 
	data_type VARCHAR(255), 
	data_length INTEGER, 
	data_precision INTEGER, 
	data_scale INTEGER, 
	null_yn VARCHAR(1), 
	pk_yn VARCHAR(1), 
	partition_key_yn VARCHAR(1), 
	cluster_key_yn VARCHAR(1), 
	update_base_yn VARCHAR(1), 
	to_single_byte_yn VARCHAR(1), 
	substr_yn VARCHAR(1), 
	comments TEXT, 
	createdon TIMESTAMP WITH TIME ZONE, 
	createdby VARCHAR(255), 
	lastupdated TIMESTAMP WITH TIME ZONE, 
	updatedby VARCHAR(255), 
	PRIMARY KEY (system_cd, instance_name, postfix, owner, table_name, column_name)
)

;


CREATE TABLE "EAPET"."TB_META_TABLES_EXT" (
	system_cd VARCHAR(32) NOT NULL, 
	instance_name VARCHAR(255) NOT NULL, 
	postfix VARCHAR(32) NOT NULL, 
	owner VARCHAR(255) NOT NULL, 
	table_name VARCHAR(255) NOT NULL, 
	database_name VARCHAR(255), 
	etl_conn_div_cd VARCHAR(32), 
	etl_conn_nm VARCHAR(255), 
	tgt_ds_cd VARCHAR(255), 
	tgt_table_name VARCHAR(255), 
	tgt_database_name VARCHAR(255), 
	instance_div_cd VARCHAR(32), 
	comments TEXT, 
	createdon TIMESTAMP WITH TIME ZONE, 
	createdby VARCHAR(255), 
	lastupdated TIMESTAMP WITH TIME ZONE, 
	updatedby VARCHAR(255), 
	sess_name_rule TEXT, 
	mapp_name_rule TEXT, 
	tgt_name_rule TEXT, 
	partition_col_modifiable_yn VARCHAR(1), 
	table_type VARCHAR(32), 
	sql_insp_yn VARCHAR(1), 
	sql_src_count INTEGER, 
	sql_tgt_count INTEGER, 
	sql_tgt_pk_dup INTEGER, 
	PRIMARY KEY (system_cd, instance_name, postfix, owner, table_name)
)

;


CREATE TABLE data_sources (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	db_type VARCHAR(40) NOT NULL, 
	host VARCHAR(255) NOT NULL, 
	port INTEGER, 
	database VARCHAR(255) NOT NULL, 
	username VARCHAR(255) NOT NULL, 
	secret_encrypted TEXT NOT NULL, 
	options JSON NOT NULL, 
	ssh_enabled BOOLEAN NOT NULL, 
	ssh_host VARCHAR(255), 
	ssh_port INTEGER NOT NULL, 
	ssh_username VARCHAR(255), 
	ssh_auth_type VARCHAR(30), 
	ssh_secret_encrypted TEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	last_tested_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;


CREATE TABLE menus (
	id SERIAL NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	label VARCHAR(80) NOT NULL, 
	path VARCHAR(200) NOT NULL, 
	icon VARCHAR(80) NOT NULL, 
	"order" INTEGER NOT NULL, 
	parent_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	FOREIGN KEY(parent_id) REFERENCES menus (id)
)

;


CREATE TABLE permissions (
	id SERIAL NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	description VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
)

;


CREATE TABLE roles (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;


CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE collection_jobs (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	data_source_id INTEGER NOT NULL, 
	schedule_type VARCHAR(20) NOT NULL, 
	cron VARCHAR(100) NOT NULL, 
	interval_minutes INTEGER, 
	schemas JSON NOT NULL, 
	collection_items JSON NOT NULL, 
	collect_storage BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	next_run_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(data_source_id) REFERENCES data_sources (id) ON DELETE CASCADE
)

;


CREATE TABLE meta_table_config (
	id INTEGER NOT NULL, 
	source_type VARCHAR(20) NOT NULL, 
	external_source_id INTEGER, 
	schema_name VARCHAR(255) NOT NULL, 
	tables_table_name VARCHAR(255) NOT NULL, 
	columns_table_name VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(external_source_id) REFERENCES data_sources (id) ON DELETE SET NULL
)

;


CREATE TABLE role_menus (
	role_id INTEGER NOT NULL, 
	menu_id INTEGER NOT NULL, 
	PRIMARY KEY (role_id, menu_id), 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(menu_id) REFERENCES menus (id) ON DELETE CASCADE
)

;


CREATE TABLE role_permissions (
	role_id INTEGER NOT NULL, 
	permission_id INTEGER NOT NULL, 
	PRIMARY KEY (role_id, permission_id), 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)

;


CREATE TABLE user_roles (
	user_id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	PRIMARY KEY (user_id, role_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
)

;


CREATE TABLE collection_runs (
	id SERIAL NOT NULL, 
	job_id INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	current_step VARCHAR(80) NOT NULL, 
	"current_schema" VARCHAR(255), 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	cancel_requested_at TIMESTAMP WITH TIME ZONE, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(80), 
	attempt_count INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	object_count INTEGER NOT NULL, 
	error_message TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES collection_jobs (id) ON DELETE CASCADE
)

;


CREATE TABLE run_logs (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	sequence INTEGER NOT NULL, 
	level VARCHAR(20) NOT NULL, 
	step VARCHAR(80) NOT NULL, 
	message TEXT NOT NULL, 
	details TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES collection_runs (id) ON DELETE CASCADE
)

;


CREATE TABLE schema_snapshots (
	id SERIAL NOT NULL, 
	data_source_id INTEGER NOT NULL, 
	run_id INTEGER NOT NULL, 
	captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	payload JSON NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(data_source_id) REFERENCES data_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES collection_runs (id) ON DELETE CASCADE
)

;

CREATE INDEX ix_data_sources_db_type ON data_sources (db_type);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_collection_jobs_data_source_id ON collection_jobs (data_source_id);

CREATE INDEX ix_collection_runs_job_id ON collection_runs (job_id);

CREATE INDEX ix_run_logs_run_id ON run_logs (run_id);

CREATE INDEX ix_run_logs_sequence ON run_logs (sequence);

CREATE INDEX ix_schema_snapshots_data_source_id ON schema_snapshots (data_source_id);

CREATE INDEX ix_schema_snapshots_fingerprint ON schema_snapshots (fingerprint);

CREATE INDEX ix_schema_snapshots_run_id ON schema_snapshots (run_id);

CREATE SCHEMA IF NOT EXISTS integration;
CREATE OR REPLACE VIEW integration.snapshot_history AS
SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at, ss.fingerprint,
       (ss.payload::jsonb)->>'source' AS source_name, (ss.payload::jsonb)->>'db_type' AS db_type,
       jsonb_array_length(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) AS schema_count
FROM schema_snapshots ss;
CREATE OR REPLACE VIEW integration.latest_snapshots AS
SELECT DISTINCT ON (data_source_id) snapshot_id, data_source_id, run_id, captured_at,
       fingerprint, source_name, db_type, schema_count
FROM integration.snapshot_history
ORDER BY data_source_id, captured_at DESC, snapshot_id DESC;
CREATE OR REPLACE VIEW integration.schema_history AS
SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
       schema_item->>'name' AS schema_name,
       jsonb_array_length(COALESCE(schema_item->'tables', '[]'::jsonb)) AS table_count,
       jsonb_array_length(COALESCE(schema_item->'views', '[]'::jsonb)) AS view_count,
       jsonb_array_length(COALESCE(schema_item->'procedures', '[]'::jsonb)) AS procedure_count
FROM schema_snapshots ss
CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item;
CREATE OR REPLACE VIEW integration.table_history AS
SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
       schema_item->>'name' AS schema_name, table_item->>'name' AS table_name,
       table_item->>'comment' AS comment
FROM schema_snapshots ss
CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(schema_item->'tables', '[]'::jsonb)) table_item;
CREATE OR REPLACE VIEW integration.column_history AS
SELECT ss.id AS snapshot_id, ss.data_source_id, ss.run_id, ss.captured_at,
       schema_item->>'name' AS schema_name, table_item->>'name' AS table_name,
       column_item->>'name' AS column_name, column_item->>'type' AS data_type,
       (column_item->>'nullable')::boolean AS nullable
FROM schema_snapshots ss
CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ss.payload::jsonb)->'schemas', '[]'::jsonb)) schema_item
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(schema_item->'tables', '[]'::jsonb)) table_item
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(table_item->'columns', '[]'::jsonb)) column_item;
COMMIT;
