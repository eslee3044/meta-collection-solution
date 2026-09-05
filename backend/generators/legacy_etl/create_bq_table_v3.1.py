import os
import argparse
from google.cloud import bigquery
import psycopg2
from psycopg2.extras import DictCursor
import sys

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-l", "--level", required=True, help="LEVEL CODE - ST / L0 / A0 / INIT")
ap.add_argument("-p", "--postfix", required=True, help="table postfix")
args = vars(ap.parse_args())

tbnm = args["table"]
sysCd = args["system"]
lvlCd = args["level"]
postfix = args["postfix"]

# Postgres Connection 연결
conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

#####################################################
#				Get Table Info
#####################################################
sqlSelTab = f"""
SELECT system_cd
	, tgt_table_name
	, MAX(database_name) database_name
	, MAX(tgt_ds_cd) tgt_ds_cd
	, MAX(instance_div_cd) instance_div_cd
	, MAX(comments) comments
FROM eapet.tb_meta_tables_ext
WHERE system_cd = '{sysCd}'
AND table_name = '{tbnm}'
AND postfix = '{postfix}'
GROUP BY system_cd, tgt_table_name, postfix
"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()

for rowTab in rsltTab:
    dbms = rowTab['database_name']
    instDivCd = rowTab['instance_div_cd']
    dsnm = rowTab['tgt_ds_cd']
    tbComments = rowTab['comments']
    tgt_tbnm = rowTab['tgt_table_name']
    break;  # 한 row만 필요함

if lvlCd != 'INIT':
    dsnmOk = lvlCd + '_' + dsnm[-4:]
if lvlCd == 'INIT':
    dsnmOk = "ST" + '_' + dsnm[-4:]

# Multiple Instance YN
if instDivCd != None and instDivCd != '':
    mult_inst_flag = "Y"
else:
    mult_inst_flag = "N"

#####################################################
#				Get Column Info
#####################################################
# 매핑을 공유하는 시스템은 인스턴스의 합집합으로 본 컬럼정보로 생성한다.
sqlSelCol = f"""
(SELECT T.system_cd
    , T.tgt_table_name
    , C.column_name     
    , MAX(C.data_type) data_type
    , coalesce(MAX(C.data_length),0) data_length
    , coalesce(MAX(C.data_precision),0) data_precision
    , coalesce(MAX(C.data_scale),0) data_scale
    , MAX(C.pk_yn) pk_yn
    , MAX(C.null_yn) null_yn
    , MAX(C.partition_key_yn) partition_key_yn
    , MAX(C.cluster_key_yn) cluster_key_yn
    , coalesce(MAX(C.comments), '') comments
    , MAX(C.column_id) column_id
FROM eapet.tb_meta_columns_ext C
INNER JOIN eapet.tb_meta_tables_ext T
ON  T.system_cd     = C.system_cd
AND T.postfix       = C.postfix
AND T.owner         = C.owner
AND T.table_name    = C.table_name
WHERE T.system_cd = '{sysCd}'
AND T.table_name = '{tbnm}' """

if sysCd not in ['GSFS', 'NBES', 'GFMS']:  # 매핑 공유 시스템들이 아닌 경우. GMES 제외(20211214.BHHAN)
    sqlSelCol += f"""AND T.postfix = '{postfix}'"""

sqlSelCol += f"""GROUP BY T.system_cd, T.tgt_table_name, C.column_name
ORDER BY tgt_table_name, column_id) """

curs.execute(sqlSelCol)
rsltCol = curs.fetchall()

rsltPttCols = []
rsltClsCols = []
for row in rsltCol:
    if row["partition_key_yn"] == "Y":
        rsltPttCols.append(row)

    if row["cluster_key_yn"] == "Y":
        rsltClsCols.append(row)

# if lvlCd == 'A0' and len(rsltPttCols) == 0:
#     print("partition key가 없으므로 A0 테이블은 만들수 없습니다.")
#     sys.exit()

# if lvlCd == 'A0' and len(rsltPttCols) == 0:
#     print("partition key가 없으므로 A0 테이블은 만들수 없습니다.")
#     exit

# # 월파티션 적용에 따라 A0 테이블은 만들지 않는다. by yeedh 2020/12/02
# if lvlCd == 'A0':
#     print("A0 테이블은 만들수 없습니다.")
#     quit()

# Construct a BigQuery client object.
client = bigquery.Client()

schema = []
# L0일 경우에는 partition key column이 존재할 때만 파티션 컬럼 만든다
if lvlCd == 'ST' or len(rsltPttCols) > 0:
    # P_PTT 컬럼은 Nullable로 수정 (김현진 책임 추가, 2020/09/03)
    schema.append(bigquery.SchemaField(name='P_PTT', field_type='DATE', mode="NULLABLE", description="파티션 일자"))

schema.append(bigquery.SchemaField(name='ETL_LOAD_TS', field_type='TIMESTAMP', mode="REQUIRED", description="적재 수집일시"))

# GSFS, NBES 시스템인 경우 INSTANCE 필드를 만든다. (김현진 책임 추가, 2020/09/03)
if sysCd == 'GSFS':
    schema.append(
        bigquery.SchemaField(name='INSTANCE', field_type='STRING', mode="REQUIRED",
                             description="인스턴스명(Asia, Russia, Europe, America)"))
elif sysCd == 'NBES':
    schema.append(
        bigquery.SchemaField(name='INSTANCE', field_type='STRING', mode="REQUIRED",
                             description="인스턴스명(LGNBHP, LGNBEP)"))
elif sysCd == 'ELQA' and mult_inst_flag == 'Y':  # ELQA의 VS인 경우 INSTANCE 컬럼 추가해서 구분(이은송K, 2024/10/21)
    schema.append(
        bigquery.SchemaField(name='INSTANCE', field_type='STRING', mode="REQUIRED",
                             description="인스턴스명(ELOQUA_VS)"))

for r, row in enumerate(rsltCol):
    v_column_name = row['column_name']
    v_data_type = row['data_type']
    v_data_length = row['data_length']
    v_data_precis = row['data_precision']
    v_data_scale = row['data_scale']
    v_nullable = row['null_yn']
    v_comments = row['comments']

    s_data_type = ''  # 매칭되는 타입이 없으면 에러가 나도록 수정 (김현진 책임,21/01/29)
    # data type
    if v_data_type.upper() in (
            'VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'CLOB', 'ROWID', 'TEXT', 'MEDIUMTEXT', 'LONGTEXT','LONG',
            'UNIQUEIDENTIFIER', 'CHARACTER VARYING', 'NCHAR'):  # LONG 추가 (오진석C,22/05/11), NCHAR 추가(박정균C, 23/01/30)
        s_data_type = 'STRING'
    elif v_data_type.upper() == 'DATE':
        # if dbms == 'Oracle':
        if dbms == 'ORACLE':  # 대문자로 수정(한병학C,21/11/11)
            s_data_type = 'TIMESTAMP'
        elif dbms in ('MySql', 'Microsoft SQL Server', 'MARIADB', "POSTGRESQL"):  # MARIADB추가(한병학C,22/01/05)
            s_data_type = 'DATE'
        else:
            s_data_type = 'DATE'
    elif v_data_type.upper() == 'TIME':
        s_data_type = 'TIME'
    elif v_data_type.upper() in ('DATETIME', 'SMALLDATETIME', 'DATETIME2'):
        s_data_type = 'DATETIME'
    elif v_data_type.upper() in ('TIMESTAMP', 'TIMESTAMP(6)',
                                 'TIMESTAMP WITHOUT TIME ZONE'):  # Postgre DB에 TIMESTAMP WITHOUT TIME ZONE 타입 존재하여 추가 (김현진C, '21/03/05)
        s_data_type = 'TIMESTAMP'
    elif v_data_type.upper() in ('NUMBER', 'DECIMAL', 'NUMERIC'):
        if v_data_precis < 30 and v_data_scale == 0:
            s_data_type = 'NUMERIC'
        else:
            s_data_type = 'BIGNUMERIC'
    elif v_data_type.upper() in ('FLOAT', 'DOUBLE', 'DOUBLE PRECISION'):
        if v_data_precis > 38 and v_data_scale == 0:
            s_data_type = 'BIGNUMERIC'
        else:
            s_data_type = 'NUMERIC'

    elif v_data_type.upper() in ('INT', 'TINYINT', 'BIGINT', 'SMALLINT', 'INTEGER', 'INT4'):  # INT4 추가 (jsoh 20240314)
        if dbms == 'DB2 UDB' and v_data_type.upper() == 'INTEGER':
            s_data_type = 'NUMERIC'
        else:
            s_data_type = 'INTEGER'
    elif v_data_type.upper() in ('BLOB', 'MEDIUMBLOB'):
        s_data_type = 'BYTES'
    elif v_data_type.upper() == 'RAW':
        s_data_type = 'BYTES'
    elif v_data_type.upper() == 'BOOLEAN':  # BOOLEAN 타입 추가 (김현진C, '21/03/05)
        s_data_type = 'BOOLEAN'
    elif v_data_type.upper() == 'BOOL':  # BOOL 타입 추가 (jsoh 20240314)
        s_data_type = 'STRING'

    if len(s_data_type) == 0:  # 매칭되는 타입이 없으면 에러가 나도록 수정 (김현진 책임,21/01/29)
        print(v_data_type.upper() + ": BQ테이블에 매칭되는 데이터타입이 없습니다")
        sys.exit()

    # null YN
    if v_nullable == "Y":
        nullYn = ""
    else:
        nullYn = "REQUIRED"

    # field generation
    schema.append(bigquery.SchemaField(name=f'{v_column_name}', field_type=f'{s_data_type}', mode=nullYn,
                                       description=f'{v_comments}'))

print(schema)

table_id = f'{os.environ.get("BQ_PROJECT_ID", "")}.{dsnmOk}.{tgt_tbnm}'
table = bigquery.Table(table_id, schema=schema)

# partition	- ST일 경우에는 DAY partition을 만든다
if lvlCd == 'ST':
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="P_PTT"
    )
# partition	- L0일 경우에는 partition key column이 존재할 때만 MONTH partition을 만든다(월파티션 적용에 따른 수정. by yeedh 2020/12/02)
elif len(rsltPttCols) > 0:
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.MONTH,
        field="P_PTT"
    )

# cluster
for row in rsltClsCols:
    table.clustering_fields = f"{row['column_name']}"
    break

# comments
table.description = tbComments

table = client.create_table(table)
# 작업완료 표시 - (이은송C, 2023.12.15)
print(table_id + ": BQ테이블이 생성되었습니다.")
