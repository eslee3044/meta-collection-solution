from app.datalake_ddl import build_table_spec, render_postgresql_ddl, render_postgresql_procedure_scripts, table_spec_fingerprint


def _metadata(**overrides):
    payload = {
        "system_cd": "TEST",
        "owner": "PUBLIC",
        "table_name": "CUSTOMERS",
        "tgt_ds_cd": "ST_TEST",
        "tgt_table_name": "CUSTOMERS",
        "columns": [
            {"column_name": "CUSTOMER_ID", "data_type": "BIGINT", "null_yn": "N", "pk_yn": "Y"},
            {"column_name": "NAME", "data_type": "VARCHAR(100)", "null_yn": "Y", "pk_yn": "N"},
            {"column_name": "UPDATED_AT", "data_type": "TIMESTAMP", "null_yn": "N", "pk_yn": "N", "update_base_yn": "Y"},
            {"column_name": "CREATED_AT", "data_type": "TIMESTAMP", "null_yn": "N", "pk_yn": "N", "partition_key_yn": "Y"},
        ],
    }
    payload.update(overrides)
    return payload


def test_build_table_spec_derives_st_l0_and_procedure_from_one_spec():
    spec = build_table_spec(_metadata())

    assert spec.strategy == "MERGE"
    assert spec.pk_columns == ("CUSTOMER_ID",)
    assert spec.update_base_columns == ("UPDATED_AT",)
    assert spec.partition_column == "CREATED_AT"
    assert spec.st_schema == "ST_TEST"
    assert spec.l0_schema == "L0_TEST"
    assert spec.st_table == "CUSTOMERS"
    assert spec.l0_table == "CUSTOMERS"
    assert spec.procedure_name == "SP_MRG_CUSTOMERS"


def test_postgresql_ddl_contains_st_l0_and_idempotent_procedure():
    ddl = render_postgresql_ddl(build_table_spec(_metadata()))

    assert 'CREATE SCHEMA IF NOT EXISTS "ST_TEST"' in ddl
    assert 'CREATE SCHEMA IF NOT EXISTS "L0_TEST"' in ddl
    assert 'CREATE TABLE IF NOT EXISTS "ST_TEST"."CUSTOMERS"' in ddl
    assert 'CREATE TABLE IF NOT EXISTS "L0_TEST"."CUSTOMERS"' in ddl
    assert 'CREATE OR REPLACE PROCEDURE "L0_TEST"."SP_MRG_CUSTOMERS"' in ddl
    assert 'p_window_start timestamptz' in ddl
    assert 'p_window_end timestamptz' in ddl
    assert 'ON CONFLICT ("CUSTOMER_ID") DO UPDATE' in ddl
    assert 'WHERE (target."UPDATED_AT" IS NULL OR target."UPDATED_AT" <= EXCLUDED."UPDATED_AT")' in ddl
    assert 'P_PTT' in ddl
    assert 'ETL_LOAD_TS' in ddl
    assert 'BATCH_ID' in ddl


def test_missing_pk_and_date_key_uses_full_snapshot_fallback():
    metadata = _metadata(
        columns=[
            {"column_name": "NAME", "data_type": "VARCHAR(100)", "null_yn": "Y", "pk_yn": "N"},
        ]
    )

    spec = build_table_spec(metadata)

    assert spec.strategy == "TRUNCATE_INSERT"
    assert spec.blocking_reasons
    assert "PK" in " ".join(spec.blocking_reasons)
    assert "날짜" in " ".join(spec.blocking_reasons)
    ddl = render_postgresql_ddl(spec)
    assert "TRUNCATE TABLE" in ddl
    assert "SP_TRUNC_INS" in ddl


def test_period_replace_ddl_does_not_create_an_empty_primary_key():
    metadata = _metadata(
        columns=[
            {"column_name": "BUSINESS_DATE", "data_type": "DATE", "null_yn": "N", "partition_key_yn": "Y"},
            {"column_name": "VALUE", "data_type": "NUMERIC(12,2)", "null_yn": "Y"},
        ]
    )

    spec = build_table_spec(metadata)
    ddl = render_postgresql_ddl(spec)

    assert spec.strategy == "PERIOD_REPLACE"
    assert "PRIMARY KEY ()" not in ddl
    assert 'DELETE FROM "L0_TEST"."CUSTOMERS"' in ddl


def test_identifier_injection_is_rejected():
    metadata = _metadata(table_name='CUSTOMERS; DROP TABLE x')

    try:
        build_table_spec(metadata)
    except ValueError as exc:
        assert "table" in str(exc)
    else:
        raise AssertionError("invalid identifier must be rejected")


def test_three_procedure_scripts_are_generated_with_recommended_default_and_reasons():
    spec = build_table_spec(_metadata())

    scripts = render_postgresql_procedure_scripts(spec)

    assert set(scripts) == {"MERGE", "DELETE_INSERT", "TRUNCATE_INSERT"}
    assert scripts["MERGE"]["recommended"] is True
    assert "PK" in scripts["MERGE"]["reason"]
    assert "ON CONFLICT" in scripts["MERGE"]["sql"]
    assert "DELETE FROM" in scripts["DELETE_INSERT"]["sql"]
    assert "TRUNCATE" in scripts["TRUNCATE_INSERT"]["sql"]


def test_unsafe_procedure_modes_are_generated_as_blocked_not_silently_applied():
    spec = build_table_spec(_metadata(columns=[
        {"column_name": "NAME", "data_type": "TEXT", "pk_yn": "N"},
        {"column_name": "BUSINESS_DATE", "data_type": "DATE", "partition_key_yn": "Y"},
    ]))

    scripts = render_postgresql_procedure_scripts(spec)

    assert scripts["MERGE"]["available"] is False
    assert "PK" in scripts["MERGE"]["reason"]
    assert scripts["DELETE_INSERT"]["available"] is True
    assert scripts["TRUNCATE_INSERT"]["available"] is True


def test_dimensions_and_nullability_are_part_of_canonical_spec_and_fingerprint():
    spec = build_table_spec(_metadata(columns=[
        {"column_name": "ID", "data_type": "VARCHAR2", "data_length": 120, "null_yn": "N", "pk_yn": "Y"},
        {"column_name": "AMOUNT", "data_type": "NUMBER", "data_precision": 12, "data_scale": 2, "null_yn": "Y", "update_base_yn": "Y"},
    ]))
    ddl = render_postgresql_ddl(spec)
    assert '"ID" VARCHAR(120) NOT NULL' in ddl
    assert '"AMOUNT" NUMERIC(12,2)' in ddl
    changed = build_table_spec(_metadata(columns=[
        {"column_name": "ID", "data_type": "VARCHAR2", "data_length": 121, "null_yn": "N", "pk_yn": "Y"},
        {"column_name": "AMOUNT", "data_type": "NUMBER", "data_precision": 12, "data_scale": 2, "null_yn": "Y", "update_base_yn": "Y"},
    ]))
    assert table_spec_fingerprint(spec) != table_spec_fingerprint(changed)
