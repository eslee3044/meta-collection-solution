import xml.etree.ElementTree as ET
import argparse
import psycopg2
from psycopg2.extras import DictCursor
import targetXmlGen
import os
from myMap import *

#write_infa_xml_v2.py -t MKT_MODEL_REVIEW_CONTENTS -s LGKR -l M -g MKT_MODEL_REVIEW_CONTENTS.xml -i rds-lgecokr-prod-mgrdb -po N

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-l", "--loadflag", required=True, help="초기적재(I), 변경적재(M)")
ap.add_argument("-g", "--tgtXml", required=False, help="Target Xml File Name (ex) CLS_MST.xml")
ap.add_argument("-i", "--instance", required=False, help="INSTANCE_NAME - multi instance일 경우 only (ex) APNGSFSP, LGNBHP ...")
ap.add_argument("-po", "--postfix", required=False, help="테이블 접미사")
ap.add_argument("-d", "--directory", required=False, help="세션파일 생성 디렉토리 지정")

args = vars(ap.parse_args())

# tgt_tbnm            = args["table"]
tbnm = args["table"]
sysCd = args["system"]
init_mod_flag = args["loadflag"]
tgtXml = args["tgtXml"]
instance_nm = args["instance"]
postfix = args["postfix"]
dir = args["directory"]

# m_filter = ""          # 변경적재시 Source Filter 용 컬럼
# m_filter_datatype = "" # 변경적재시 Source Filter 용 컬럼 Data Type
# m_filter_length = 0    # 변경적재시 Source Filter 용 컬럼 Length
m_filters = []  # 변경적재시 Source Filter 용 - (name, datatype, length)의 list임

# Postgres Connection 연결
conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

#####################################################
#       Get Table Info
#####################################################

sqlSelTab = f"""
SELECT system_cd
  , instance_name
  , postfix
  , owner
  , table_name
  , database_name
  , etl_conn_div_cd
  , etl_conn_nm
  , tgt_ds_cd
  , substring(tgt_ds_cd,-4) as tgt_ds_digit4
  , tgt_table_name
  , tgt_database_name
  , instance_div_cd
  , sess_name_rule
  , mapp_name_rule
  , tgt_name_rule
FROM eapet.tb_meta_tables_ext
WHERE 1=1
AND system_cd = '{sysCd}'
AND table_name = '{tbnm}'
AND instance_name = '{instance_nm}'
AND postfix = '{postfix}'"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()
for rowTab in rsltTab:
    inst_name = rowTab['instance_name']
    ownernm = rowTab['owner']
    srctbnm = rowTab['table_name']
    dbms = rowTab['database_name']
    connSubType = rowTab['etl_conn_div_cd']
    connnm = rowTab['etl_conn_nm']
    tgtTbnm = rowTab['tgt_table_name']
    tgtDbms = rowTab['tgt_database_name']
    dsnm = rowTab['tgt_ds_cd']
    dsnm_digit4 = rowTab['tgt_ds_digit4']
    instDivCd = rowTab['instance_div_cd']
    sessNmRl = rowTab['sess_name_rule']
    mappNmRl = rowTab['mapp_name_rule']
    tgtNmRl = rowTab['tgt_name_rule']

    break;  # 한 row만 필요함

dbtype = dbtypeMap[dbms]

output_file_name = f"[{inst_name}]{dsnm}.{tgtTbnm}(적재쿼리)"

#####################################################
#       Get Column Info
#####################################################
# GMES, GSFS, NBES 의 경우 mapping을 공유하기 위해 instance들의 합집합을 사용한다.
sqlSelCol = f"""
SELECT x.system_cd
  , x.table_name
  , x.column_name
  , x.column_id
  , x.data_type
  , x.data_length
  , x.data_precision
  , x.data_scale
  , x.null_yn
  , x.pk_yn
  , x.partition_key_yn
  , x.cluster_key_yn
  , x.update_base_yn
  , x.to_single_byte_yn
  , x.substr_yn
  , case when y.column_name is null then 'N' else 'Y' end inst_exist_yn
FROM
  (SELECT c.system_cd
    , c.owner
    , c.table_name
    , c.column_name
    , max(c.column_id) column_id
    , max(c.data_type) data_type
    , coalesce(max(c.data_length),0) data_length
    , coalesce(max(c.data_precision),0) data_precision
    , coalesce(max(c.data_scale),0) data_scale
    , max(c.null_yn) null_yn
    , max(c.pk_yn) pk_yn
    , max(c.partition_key_yn) partition_key_yn
    , max(c.cluster_key_yn) cluster_key_yn
    , max(c.update_base_yn) update_base_yn
    , max(c.to_single_byte_yn) to_single_byte_yn
    , max(c.substr_yn) substr_yn
  FROM eapet.tb_meta_columns_ext c
  WHERE 1=1 
    AND c.system_cd = '{sysCd}'
    AND c.table_name = '{tbnm}' """

if sysCd not in ['GMES', 'GSFS', 'NBES', 'GFMS']:
    sqlSelCol += f"""AND c.postfix = '{postfix}'"""

sqlSelCol += f"""
  AND EXISTS
    ( SELECT 1
        FROM eapet.tb_meta_tables_ext t
       WHERE t.system_cd     = c.system_cd
         AND t.instance_name = c.instance_name
         AND t.owner         = c.owner
         AND t.table_name    = c.table_name
         AND t.table_name    = '{tbnm}'
    )
"""
# if instance_nm != None: # GMES나 OBS_, TMS_와 같이 소스테이블과 타겟테이블명이 다른 경우에 해당(20/12/15 김현진c)
#  sqlSelCol += f"         AND TGT_TABLE_NAME = '{tgt_tbnm}_{instance_nm}')"
# else:
#  sqlSelCol += f"         AND TGT_TABLE_NAME = '{tgt_tbnm}')"

sqlSelCol += f"""
  GROUP BY c.system_cd, c.owner, c.table_name, c.column_name
  ) x -- instance 합집합
LEFT OUTER JOIN
  (SELECT c.system_cd
    , c.instance_name
    , c.owner
    , c.table_name
    , c.column_name
  FROM eapet.tb_meta_columns_ext c
  WHERE c.system_cd = '{sysCd}'
  AND c.table_name = '{tbnm}' 
  AND c.instance_name = '{instance_nm}'
"""

if sysCd not in ['GMES', 'GSFS', 'NBES', 'GFMS']:
    sqlSelCol += f"""AND c.postfix = '{postfix}'"""

sqlSelCol += f"""
  AND EXISTS
    ( SELECT 1
        FROM eapet.tb_meta_tables_ext t
       WHERE t.system_cd     = c.system_cd
         AND t.instance_name = c.instance_name
         AND t.owner         = c.owner
         AND t.table_name    = c.table_name
         AND t.table_name    = '{tbnm}'
    )
  ) y -- 현재 instance    
ON x.system_cd = y.system_cd
AND x.owner = y.owner
AND x.table_name = y.table_name
AND x.column_name = y.column_name
ORDER BY x.system_cd, x.table_name, x.column_id
"""

# print(sqlSelCol)

curs.execute(sqlSelCol)
rsltCol = curs.fetchall()
for rowCol in rsltCol:
    if rowCol['update_base_yn'] == "Y":
        # m_filter = rowCol['COLUMN_NAME']
        # m_filter_datatype = rowCol['DATA_TYPE']
        # m_filter_length = rowCol['DATA_LENGTH']
        m_filters.append((rowCol['column_name'], rowCol['data_type'], rowCol['data_length']))

# 디렉토리 추가
if dir != None:
    dir = dir + '/'
    folder_path = os.path.join(os.getcwd(), f'ds_source_sql/{dir}')
    # print(f"folder_path : {folder_path}")
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            # print(f"dir : {dir}")
        except Exception as e:
            print(f"폴더 생성 중 오류 발생: {e}")
else:
    dir = ''

f = open(f'ds_source_sql/{dir}{output_file_name}.txt', 'w', encoding='utf-8')

print(f"DS 소스 쿼리 경로&파일명 : ds_source_sql/{dir}{output_file_name}.txt")

for r, row in enumerate(rsltCol):
    # print (row)
    # DATATYPE : varchar2 / char / number / number(p,s) / date / blob
    # FIELDNUMBER : column_id
    # KEYTYPE : PRIMARY KEY vs NOT A KEY
    # LENGTH : VARCHAR2/CHAR - 0, DATE - 19, number - 24, mumber(p,s) - p+2, blob - 8000
    # NAME : column_name
    # NULLABLE : NOTNULL / NULL
    # PHYSICALLENGTH : = precision
    # PRECISION : VARCHAR2/CHAR = data_length, DATE - 19, number - 15, mumber(p,s) - p, blob - 4000
    # SCALE : 0, mumber(p,s) - s

    v_column_name = row['column_name']
    v_data_type = row['data_type']
    v_data_length = row['data_length']
    v_data_precis = row['data_precision']
    v_data_scale = row['data_scale']
    v_nullable = row['null_yn']
    v_column_id = r
    v_pk_yn = row['pk_yn']

    # print(f"{v_column_name} / {v_data_precis}")
    # set data_type
    if dbms == 'ORACLE':
        if v_data_type == 'NUMBER' and v_data_precis > 0:
            s_data_type = 'number(p,s)'
        elif v_data_type == 'BINARY_DOUBLE':  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
            s_data_type = 'number(p,s)'  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        elif v_data_type == 'BINARY_FLOAT':
            s_data_type = 'number(p,s)'           
        elif v_data_type == 'FLOAT':
            s_data_type = 'number(p,s)'
        elif v_data_type == 'ROWID':
            s_data_type = 'varchar2'
        elif v_data_type == 'TIMESTAMP(6)':
            s_data_type = 'timestamp'
        elif v_data_type in ('DATE', 'TIMESTAMP'):
            s_data_type = v_data_type.lower()
        elif v_data_type in ('BLOB', 'RAW', 'LONG RAW'):
            s_data_type = v_data_type.lower()
        else:
            s_data_type = v_data_type.lower()
    elif dbms in ['MYSQL', 'MARIADB']:
        if v_data_type in ('DATE', 'TIMESTAMP'):
            s_data_type = v_data_type.lower()
        elif v_data_type in ('DATETIME'):
            s_data_type = 'timestamp'
        elif v_data_type in ('INT', 'TINYINT', 'SMALLINT'):
            s_data_type = 'integer'
        elif v_data_type in ('DOUBLE'):  # MYSQL DOUBLE 존재 확인하여 반영 ('24/03/19, 이은송)
            s_data_type = 'float'
        elif v_data_type in ('BLOB', 'MEDIUMBLOB'):
            s_data_type = 'longvarbinary'
        elif v_data_type in ('MEDIUMTEXT', 'LONGTEXT'):
            s_data_type = 'text'
        else:
            s_data_type = v_data_type.lower()
    elif dbms == 'MS SQL SERVER':
        if v_data_type in (
                'DATETIME', 'SMALLDATETIME', 'DATETIME2'):  # MSSQL SMALLDATETIME 존재 확인하여 반영 ('21/02/08, 김현진C)
            s_data_type = 'datetime'
        elif v_data_type in ('INT', 'TINYINT', 'SMALLINT'):
            s_data_type = 'int'
        elif v_data_type in ('UNIQUEIDENTIFIER'):  # MSSQL UNIQUEIDENTIFIER 존재 확인하여 반영 ('21/04/14, 한병학C)
            s_data_type = 'nvarchar'
        else:
            s_data_type = v_data_type.lower()
    elif dbms == 'Vertica':
        if v_data_type in ('INT', 'TINYINT', 'BIGINT', 'SMALLINT'):
            s_data_type = 'bigint'
        else:
            s_data_type = v_data_type.lower()
    elif dbms == 'POSTGRESQL':  # Postgre 추가 ('21/03/05, 김현진C)
        if v_data_type in ('DATETIME', 'SMALLDATETIME'):
            s_data_type = 'datetime'
        elif v_data_type in ('INT', 'TINYINT', 'SMALLINT', 'INTEGER'):
            s_data_type = 'integer'
        elif v_data_type in ('BIGINT'):
            s_data_type = 'bigint'
        elif v_data_type in ('NUMERIC', 'DOUBLE PRECISION'): # DOUBLE PRECISION 추가 20240409 jsoh
            s_data_type = 'numeric'
        elif v_data_type in ('MEDIUMTEXT', 'LONGTEXT', 'TEXT', 'BOOLEAN', 'CHARACTER VARYING'):
            s_data_type = 'text'
        elif v_data_type in ('TIMESTAMP WITHOUT TIME ZONE', 'TIMESTAMP'):
            s_data_type = 'timestamp'
        elif v_data_type in ('DATE'):
            s_data_type = v_data_type.lower()
    elif dbms == 'DB2 UDB':
        if v_data_type in (
        'BINARY_DOUBLE', 'INTEGER'):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
            s_data_type = 'numeric'
        elif v_data_type in ('DOUBLE'):
            s_data_type = 'float'
        else:
            s_data_type = v_data_type.lower()

    # set pk yn
    if v_pk_yn == 'Y':
        s_pk_yn = 'PRIMARY KEY'
    else:
        s_pk_yn = 'NOT A KEY'

    # set length
    if v_data_type in (
            'VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB', 'ROWID', 'TEXT', 'MEDIUMTEXT', 'LONGTEXT',
            'ENUM', 'CHARACTER VARYING'):
        s_length = 0
    elif v_data_type in (
            'DATE', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME', 'SMALLDATETIME', 'DATETIME2', 'TIMESTAMP WITHOUT TIME ZONE'):
        s_length = 19
    elif v_data_type == 'NUMBER' and v_data_precis > 0:
        s_length = v_data_precis + 2
    elif (v_data_type == 'NUMBER' and v_data_precis == 0) or v_data_type == 'NUMERIC':
        s_length = 24
    elif v_data_type == 'DECIMAL':
        s_length = v_data_precis + 2
    elif v_data_type in ('REAL', 'FLOAT', 'DOUBLE', 'BINARY_DOUBLE', 'BINARY_FLOAT', 'DOUBLE PRECISION'):  # DOUBLE PRECISION 추가 20240409 jsoh /  PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        s_length = 24
    elif v_data_type in ('BLOB', 'MEDIUMBLOB'):
        s_length = 8000
    elif v_data_type in ('RAW', 'LONG RAW'):
        s_length = 200
    elif v_data_type in ('INT', 'TINYINT', 'SMALLINT', 'INTEGER'):
        s_length = 11
    elif v_data_type in ('BIGINT', 'MONEY'):  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_length = 19
    elif v_data_type in ('BOOLEAN'):
        s_length = 0

    # print("nm=%s, dt = %s, prec=%d, len=%d"%(v_column_name, v_data_type, v_data_precis, s_length))
    # set precision
    if v_data_type in (
            'VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB', 'ROWID', 'TEXT', 'MEDIUMTEXT',
            'LONGTEXT',
            'ENUM', 'BOOLEAN', 'CHARACTER VARYING'):
        if v_data_length > 0:
            s_precision = v_data_length
        else:
            s_precision = 80000

    elif v_data_type == 'DATE':
        if dbms == 'ORACLE':
            s_precision = 19  # YYYY-MM-DD HH24:MI:SS
        elif dbms in ['MYSQL','MARIADB','POSTGRESQL']:
            s_precision = 10  # YYYY-MM-DD
    elif v_data_type in ('DATETIME', 'SMALLDATETIME', 'DATETIME2'):
        if dbms in ['MYSQL', 'MARIADB']:
            s_precision = 29
        elif dbms == 'MS SQL SERVER':
            s_precision = 23
    elif v_data_type in ('TIMESTAMP', 'TIMESTAMP(6)', 'TIMESTAMP WITHOUT TIME ZONE'):
        if dbms == 'ORACLE':
            s_precision = 26
        elif dbms in ['MYSQL', 'MARIADB']:
            s_precision = 29
        elif dbms == 'MS SQL SERVER':
            s_precision = 8
        elif dbms == 'POSTGRESQL':
            s_precision = 29		# 19 -> 29 20240409 jsoh
        elif dbms == 'DB2 UDB':
            s_precision = 26

    elif v_data_type == 'NUMBER' and v_data_precis > 0:
        s_precision = v_data_precis
    elif v_data_type == 'NUMBER' and v_data_precis == 0:
        # s_precision = 24
        s_precision = 15
    elif v_data_type in ('DECIMAL', 'NUMERIC', 'DOUBLE PRECISION'):
        if v_data_precis == 0 or v_data_precis == None:
            s_precision = 10
        else:
            s_precision = v_data_precis
    elif v_data_type in (
            'REAL', 'FLOAT', 'DOUBLE', 'BINARY_DOUBLE'):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        s_precision = 15
    elif v_data_type in ('BLOB', 'MEDIUMBLOB'):
        s_precision = 8000
    elif v_data_type in ('RAW', 'LONG RAW'):
        s_precision = 200
    elif v_data_type in ('BIGINT', 'MONEY'):  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_precision = 19
    elif v_data_type in ('INT', 'TINYINT', 'SMALLINT', 'INTEGER'):
        if dbms == 'Vertica':
            s_precision = 19
        else:
            s_precision = 10

    # maximum precision check
    if s_precision > 104857600:
        s_precision = 104857600

    # set scale
    if v_data_type == 'NUMBER' and v_data_precis > 0:
        s_scale = v_data_scale
    elif v_data_type in ('DECIMAL', 'NUMERIC'):
        s_scale = v_data_scale
    elif v_data_type in ('DATETIME', 'SMALLDATETIME', 'DATETIME2'):
        if dbms in ['MYSQL', 'MARIADB']:
            s_scale = 9
        elif dbms == 'MS SQL SERVER':
            s_scale = 3
    elif v_data_type in ('TIMESTAMP', 'TIMESTAMP(6)', 'TIMESTAMP WITHOUT TIME ZONE'):
        if dbms == 'ORACLE':
            s_scale = 6
        elif dbms in ['MYSQL', 'MARIADB']:
            s_scale = 9
        elif dbms == 'MS SQL SERVER':
            s_scale = 0
        elif dbms == 'POSTGRESQL':
            s_scale = 9
        elif dbms == 'DB2 UDB':
            s_scale = 6
    elif v_data_type in ('MONEY'):  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_scale = 4
    else:
        s_scale = 0

    # set nullable
    if v_nullable == 'Y':
        s_nullable = 'NULL'
    else:
        s_nullable = 'NOTNULL'

#####################################################
#       SQ XML
#####################################################
for r, row in enumerate(rsltCol):
    # DATATYPE : date/time, string, timestamp, decimal
    # NAME : column_name
    # PRECISION : VARCHAR2/CHAR = data_length, DATE - 19, number - 15, mumber(p,s) - p, blob - 4000
    # SCALE : 0, mumber(p,s) - s

    v_column_name = row['column_name']
    v_data_type = row['data_type']
    v_data_length = row['data_length']
    v_data_precis = row['data_precision']
    v_data_scale = row['data_scale']
    v_nullable = row['null_yn']
    v_column_id = r
    v_pk_yn = row['pk_yn']

    # set data_type
    if v_data_type == 'NUMBER' and v_data_precis > 0:
        s_data_type = 'decimal'
    elif v_data_type == 'NUMBER' and v_data_precis == 0:
        s_data_type = 'decimal'
    elif v_data_type == 'DECIMAL':
        s_data_type = 'decimal'
    elif v_data_type in ('NUMERIC', 'DOUBLE PRECISION'):
        s_data_type = 'decimal'
    elif v_data_type in ('FLOAT', 'BINARY_DOUBLE', 'BINARY_FLOAT'):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        s_data_type = 'decimal'
    elif v_data_type in ('DOUBLE'):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        s_data_type = 'double'
    elif v_data_type in (
            'VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'NCHAR', 'ROWID', 'ENUM', 'CHARACTER VARYING'):
        s_data_type = 'string'
    elif v_data_type in ('CLOB', 'TEXT', 'MEDIUMTEXT', 'LONGTEXT'):
        s_data_type = 'text'
    elif v_data_type in ('DATE', 'DATETIME', 'SMALLDATETIME', 'DATETIME2'):
        s_data_type = 'date/time'
    elif v_data_type in ('TIMESTAMP', 'TIMESTAMP(6)', 'TIMESTAMP WITHOUT TIME ZONE'):
        s_data_type = 'date/time'
    elif v_data_type in ('BLOB', 'RAW', 'MEDIUMBLOB', 'LONG RAW'):
        s_data_type = 'binary'
    elif v_data_type == 'BIGINT':
        s_data_type = 'bigint'
    elif v_data_type in ('INT', 'TINYINT', 'SMALLINT', 'INTEGER'):
        if dbms == 'Vertica':
            s_data_type = 'bigint'
        elif dbms == 'DB2 UDB':
            s_data_type = 'decimal'
        else:
            s_data_type = 'integer'
    elif v_data_type in ('BOOLEAN'):
        if dbms == 'POSTGRESQL':
            s_data_type = 'text'
    elif v_data_type == 'MONEY':  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_data_type = 'decimal'

    # set precision
    if v_data_type in (
            'VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'NCHAR', 'ROWID', 'ENUM', 'CHARACTER VARYING'):
        if v_data_length > 0:
            s_precision = v_data_length
        else:
            s_precision = 80000
    elif v_data_type == 'BOOLEAN':
        if dbms == 'POSTGRESQL':
            s_precision = 80000
        else:
            s_precision = 10
    elif v_data_type == 'DATE':
        s_precision = 29
    elif v_data_type in ('DATETIME', 'SMALLDATETIME', 'DATETIME2'):
        s_precision = 29
    elif v_data_type in ('TIMESTAMP', 'TIMESTAMP(6)', 'TIMESTAMP WITHOUT TIME ZONE'):
        s_precision = 29
    elif v_data_type == 'NUMBER':
        if v_data_precis == 0 or v_data_scale > 9 or v_data_precis > 28:
            s_precision = 28
        else:
            s_precision = v_data_precis
    elif v_data_type == 'DECIMAL':
        if v_data_scale > 9 or v_data_precis > 28:
            s_precision = 28
        else:
            s_precision = v_data_precis
    elif v_data_type in ('NUMERIC', 'DOUBLE PRECISION'):
        if v_data_scale > 9 or v_data_precis > 28:
            s_precision = 28
        elif v_data_scale == 0 or v_data_scale == None:
            s_presicion = 28
        else:
            s_precision = v_data_precis
    elif v_data_type in ('FLOAT', 'DOUBLE', 'BINARY_DOUBLE', 'BINARY_FLOAT'):  #  PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        if v_data_type == 'DOUBLE' and dbms == 'DB2 UDB':
            s_precision = 15
        else:
            s_precision = 28

    elif v_data_type in ('BLOB', 'MEDIUMBLOB'):
        s_precision = 4000
    elif v_data_type in ('RAW', 'LONG RAW'):
        s_precision = 200
    elif v_data_type in ('CLOB', 'TEXT', 'MEDIUMTEXT', 'LONGTEXT'):
        if v_data_length > 0:
            s_precision = v_data_length
        else:
            s_precision = 80000
    elif v_data_type == 'BIGINT':
        s_precision = 19
    elif v_data_type in ('INT', 'TINYINT', 'SMALLINT', 'INTEGER'):
        if dbms == 'Vertica':
            s_precision = 19
        else:
            s_precision = 10
    elif v_data_type == 'MONEY':  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_precision = 19

    # maximum precision check
    if s_precision > 104857600:
        s_precision = 104857600

    # set scale
    if v_data_type == 'NUMBER':
        if v_data_precis == 0 or v_data_scale > 9:
            s_scale = 9
        else:
            s_scale = v_data_scale
    elif v_data_type == 'DECIMAL':
        if v_data_scale > 9:
            s_scale = 9
        else:
            s_scale = v_data_scale
    elif v_data_type == 'NUMERIC':
        if v_data_scale > 9:
            s_scale = 9
        else:
            s_scale = v_data_scale
    elif v_data_type in ('FLOAT', 'DOUBLE', 'BINARY_DOUBLE', 'BINARY_FLOAT'):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
        if dbms == 'DB2 UDB' and v_data_type in ('DOUBLE'):
            s_scale = 0
        else:
            s_scale = 9
    elif v_data_type in (
            'DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'SMALLDATETIME', 'DATETIME2',
            'TIMESTAMP WITHOUT TIME ZONE'):
        s_scale = 9
    elif v_data_type == 'MONEY':  # MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
        s_scale = 4
    else:
        s_scale = 0

#####################################################
#       SESSION XML
#####################################################
### get sql query
sql_query = "SELECT "

for r, row in enumerate(rsltCol):

    v_column_name = row['column_name']
    v_data_type = row['data_type']
    v_data_length = row['data_length']
    v_data_precis = row['data_precision']
    v_data_scale = row['data_scale']
    v_nullable = row['null_yn']
    v_pk_yn = row['pk_yn']
    v_inst_exist_yn = row['inst_exist_yn']
    v_single_byte_yn = row['to_single_byte_yn']
    v_substr_yn = row['substr_yn']
    v_column_id = r

    if r > 0:
        sql_query = sql_query + "\n     , "

    #if r > 1:
    #    sql_query = sql_query + "\t"

    #print(sql_query)
    #print(r)

    if v_inst_exist_yn == 'N':  # 현 instance 테이블에 컬럼이 없으면 걍 null
        sql_query = sql_query + "null AS " + v_column_name
    elif v_data_type in ('NUMBER', 'DECIMAL', 'NUMERIC') and (v_data_precis == 0 or v_data_scale > 9):
        if v_substr_yn == 'Y':  # overflow 에러 방지용
            if dbms == 'ORACLE':
                sql_query = sql_query + "to_number(SUBSTR(TO_CHAR(round(" + v_column_name + ",9)), 1, 19)) AS " + v_column_name
            elif dbms in ['MYSQL', 'MARIADB']:
                sql_query = sql_query + "SUBSTR(round(" + v_column_name + ",9), 1, 19) AS " + v_column_name
            elif dbms == 'MS SQL SERVER':
                sql_query = sql_query + "LEFT(round(" + v_column_name + ",9), 19) AS " + v_column_name
            elif dbms == 'Vertica':
                sql_query = sql_query + "LEFT(round(" + v_column_name + ",9), 19) AS " + v_column_name
        else:
            sql_query = sql_query + "round(" + v_column_name + ",9) AS " + v_column_name
    else:
        if v_single_byte_yn == 'Y':  # partial multibyte 에러 방지용
            sql_query = sql_query + "to_single_byte(" + v_column_name + ") AS " + v_column_name
        else:
            sql_query = sql_query + v_column_name

if instDivCd != None and instDivCd != '':  # INSTANCE 컬럼 추가
    sql_query = sql_query + f"\n     , '{instDivCd}' AS INSTANCE"

if dbms in ['MYSQL', 'MARIADB']:
    sql_query = sql_query + f"\n  FROM " + f"{ownernm}.{srctbnm}".lower()
else:
    sql_query = sql_query + f"\n  FROM {ownernm}.{srctbnm}"

if dbms == 'MS SQL SERVER':
    sql_query = sql_query + " WITH (NOLOCK)"

if len(m_filters) == 0:
    src_filter = ""
else:
    src_filter = "\n   AND ( "
    for r, m_filter_mbr in enumerate(m_filters):
        m_filter = m_filter_mbr[0]
        m_filter_datatype = m_filter_mbr[1]

        if r > 0:
            src_filter = src_filter + " OR "

        if m_filter_datatype in ("DATE", "TIMESTAMP", "TIMESTAMP(6)", "DATETIME", "DATETIME2", "TIMESTAMP WITHOUT TIME ZONE"):
            if dbms in ['ORACLE','POSTGRESQL']: # POSTGRESQL 추가 20240411 jsoh
                src_filter = src_filter + f" {m_filter} >= TO_DATE('#$P_BF1_BASE_DATE#', 'YYYYMMDD') AND {m_filter} < TO_DATE('#$P_BASE_DATE#', 'YYYYMMDD') + 1"
            elif dbms in ['MYSQL', 'MARIADB']:
                src_filter = src_filter + f" {m_filter} >= STR_TO_DATE('#$P_BF1_BASE_DATE#', '%Y%m%d') AND {m_filter} < DATE_ADD(STR_TO_DATE('#$P_BASE_DATE#', '%Y%m%d'), INTERVAL 1 DAY)"
            elif dbms == 'MS SQL SERVER':
                src_filter = src_filter + f" {m_filter} >= CONVERT(DATETIME, '#$P_BF1_BASE_DATE#', 112) AND {m_filter} < DATEADD(day, 1, CONVERT(DATETIME, '#$P_BASE_DATE#', 112))"
            elif dbms == 'Vertica':
                src_filter = src_filter + f" {m_filter} >= TO_TIMESTAMP('#$P_BF1_BASE_DATE#', 'YYYYMMDD') AND {m_filter} < TIMESTAMPADD(day, 1, TO_TIMESTAMP('#$P_BASE_DATE#', 'YYYYMMDD'))"
            elif dbms == 'DB2 UDB':  # 분할 초기적재 DB2 TIMESTAMP타입 추가 (이은송, 23/11/07)
                src_filter = src_filter + f" {m_filter} >= TIMESTAMP(SUBSTR('#$P_BF1_BASE_DATE#',1,4)||'-'||SUBSTR('#$P_BF1_BASE_DATE#',5,2)||'-'||SUBSTR('#$P_BF1_BASE_DATE#',7,2)||' 00:00:00.000') AND {m_filter} < TIMESTAMP(SUBSTR('#$P_BASE_DATE#',1,4)||'-'||SUBSTR('#$P_BASE_DATE#',5,2)||'-'||SUBSTR('#$P_BASE_DATE#',7,2)||' 00:00:00.000')"
        elif m_filter_datatype in ("VARCHAR2", "VARCHAR", "NVARCHAR", "NVARCHAR2", "CHAR", "CHARACTER VARYING"):
            src_filter = src_filter + f" {m_filter} >= '#$P_BF1_BASE_DATE#' AND {m_filter} < '#$P_BASE_DATE#999999'"

    src_filter = src_filter + ")"

if src_filter != "":
    sql_query = sql_query + f"\n WHERE 1=1 {src_filter}"

#DB2는 SELECT절 마지막에 WITH UR 붙이기 ('24/09/23, 이은송)
if dbms == 'DB2 UDB':
    sql_query = sql_query + " WITH UR"

f.write(sql_query)

f.close()

                        