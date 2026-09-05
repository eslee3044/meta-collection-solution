import xml.etree.ElementTree as ET
import argparse
import psycopg2
from psycopg2.extras import DictCursor
import targetXmlGen
import os
from myMap import *

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-l", "--loadflag", required=True, help="초기적재(I), 변경적재(M)")
ap.add_argument("-g", "--tgtXml", required=False, help="Target Xml File Name (ex) CLS_MST.xml")
ap.add_argument("-i", "--instance", required=False, help="INSTANCE_NAME - multi instance일 경우 only (ex) APNGSFSP, LGNBHP ...")
ap.add_argument("-po", "--postfix", required=False, help="테이블 접미사")
ap.add_argument("-f", "--fromval", required=False, help="session 분리 from 값")
ap.add_argument("-o", "--toval", required=False, help="session 분리 to 값")
ap.add_argument("-q", "--seq", required=False, help="session 분리 sequence")
ap.add_argument("-x", "--index", required=False, help="index hint를 위한 index name")
#ap.add_argument("-n", "--hint", required=False, help="hint 부여")
ap.add_argument("-v", "--divcol", required=False, help="session 분리 기준 column name")
ap.add_argument("-m", "--datefmt", required=False, help="session 분리 기준값 date format")
ap.add_argument("-p", "--partition", required=False, help="partition name (ex) PH_ORG_ID_005")
ap.add_argument("-ac", "--addCondition", required=False, help="추가 조건 (ex) TRANSFER_FLAG2 = 'N'")
ap.add_argument("-d", "--directory", required=False, help="세션파일 생성 디렉토리 지정")
args = vars(ap.parse_args())

# tgt_tbnm            = args["table"]
tbnm = args["table"]
sysCd = args["system"]
init_mod_flag = args["loadflag"]
tgtXml = args["tgtXml"]
instance_nm = args["instance"]
postfix = args["postfix"]
sess_div_from_val = args["fromval"]
sess_div_to_val = args["toval"]
sess_div_seq = args["seq"]
index_nm = args["index"]
#hint_nm = args["hint"]
sess_div_col = args["divcol"]
sess_div_col_date_fmt = args["datefmt"]
part_nm = args["partition"]
addCondition_val = args["addCondition"]
dir = args["directory"]

sess_div_col_datatype = ""

# m_filter = ""          # 변경적재시 Source Filter 용 컬럼
# m_filter_datatype = "" # 변경적재시 Source Filter 용 컬럼 Data Type
# m_filter_length = 0    # 변경적재시 Source Filter 용 컬럼 Length
m_filters = []  # 변경적재시 Source Filter 용 - (name, datatype, length)의 list임

foldernm = 'xml_gen'

# MySQL Connection 연결
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

# session name rule - (ex) GMES,GSFS,NBES,GFMS: 's_m_%SYSTEM_CD%_%INSTANCE_NAME%_%TABLE_NAME% / 그외: 's_m_%SYSTEM_CD%_%TGT_TABLE_NAME%'
# mapping name rult - (ex) GMES,GSFS,NBES,GFMS: 'm_%SYSTEM_CD%_%TABLE_NAME%                   / 그외: 'm_%SYSTEM_CD%_%TGT_TABLE_NAME%
# target name rule  - (ex) GMES,GSFS,NBES,GFMS: '%SYSTEM_CD%_%TABLE_NAME%                     / 그외: '%SYSTEM_CD%_%TGT_TABLE_NAME%
sess_name = sessNmRl.replace('%SYSTEM_CD%', sysCd).replace('%INSTANCE_NAME%', inst_name).replace('%OWNER%',
                                                                                                 ownernm).replace(
    '%TABLE_NAME%', srctbnm).replace('%DATABASE_NAME%', dbms) \
    .replace('%TGT_DS_CD%', dsnm).replace('%TGT_DS_DIGIT4%', dsnm_digit4).replace('%TGT_TABLE_NAME%', tgtTbnm).replace(
    '%TGT_DATABASE_NAME%', tgtDbms).replace('%INSTANCE_DIV_CD%', (instDivCd or ''))
mapp_name = mappNmRl.replace('%SYSTEM_CD%', sysCd).replace('%INSTANCE_NAME%', inst_name).replace('%OWNER%',
                                                                                                 ownernm).replace(
    '%TABLE_NAME%', srctbnm).replace('%DATABASE_NAME%', dbms) \
    .replace('%TGT_DS_CD%', dsnm).replace('%TGT_DS_DIGIT4%', dsnm_digit4).replace('%TGT_TABLE_NAME%', tgtTbnm).replace(
    '%TGT_DATABASE_NAME%', tgtDbms).replace('%INSTANCE_DIV_CD%', (instDivCd or ''))
tgt_name = tgtNmRl.replace('%SYSTEM_CD%', sysCd).replace('%INSTANCE_NAME%', inst_name).replace('%OWNER%',
                                                                                               ownernm).replace(
    '%TABLE_NAME%', srctbnm).replace('%DATABASE_NAME%', dbms) \
    .replace('%TGT_DS_CD%', dsnm).replace('%TGT_DS_DIGIT4%', dsnm_digit4).replace('%TGT_TABLE_NAME%', tgtTbnm).replace(
    '%TGT_DATABASE_NAME%', tgtDbms).replace('%INSTANCE_DIV_CD%', (instDivCd or ''))

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
  , case when Y.column_name is null then 'N' else 'Y' end inst_exist_yn
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
  ) x-- instance 합집합
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

    if rowCol['column_name'] == sess_div_col:
        sess_div_col_datatype = rowCol['data_type']

# 디렉토리 추가
if dir != None:
    dir = dir + '/'
    folder_path = os.path.join(os.getcwd(), f'session/{dir}')
    # print(f"folder_path : {folder_path}")
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            # print(f"dir : {dir}")
        except Exception as e:
            print(f"폴더 생성 중 오류 발생: {e}")
else:
    dir = ''

# 세션 분리
if sess_div_seq != None:
    sess_name = sess_name + '_' + sess_div_seq

f = open(f'session/{dir}{sess_name}.xml', 'w', encoding='utf-8')

print(f"세션 경로&파일명 : session/{dir}{sess_name}.xml")

#####################################################
#       Source XML
#####################################################
# GSFS와 GMES, NBES는 스키마정보를 공유한다.
if sysCd == 'GMES' and inst_name == 'GMESHQP':
    f.write(
        f"""    <SOURCE BUSINESSNAME ="" DATABASETYPE ="{dbtype}" DBDNAME ="{sysCd}" DESCRIPTION ="" NAME ="{srctbnm}_GV" OBJECTVERSION ="1" OWNERNAME ="{ownernm}" VERSIONNUMBER ="1">
  """)
elif sysCd in ['GSFS', 'GMES', 'NBES', 'GFMS']:
    f.write(
        f"""    <SOURCE BUSINESSNAME ="" DATABASETYPE ="{dbtype}" DBDNAME ="{sysCd}" DESCRIPTION ="" NAME ="{srctbnm}" OBJECTVERSION ="1" OWNERNAME ="{ownernm}" VERSIONNUMBER ="1">
  """)
else:
    f.write(
        f"""    <SOURCE BUSINESSNAME ="" DATABASETYPE ="{dbtype}" DBDNAME ="{sysCd}{postfix.replace('N', '')}" DESCRIPTION ="" NAME ="{srctbnm}" OBJECTVERSION ="1" OWNERNAME ="{ownernm}" VERSIONNUMBER ="1">
  """)

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

    f.write(
        f'        <SOURCEFIELD BUSINESSNAME ="" DATATYPE ="{s_data_type}" DESCRIPTION ="" FIELDNUMBER ="{v_column_id}" FIELDPROPERTY ="0" FIELDTYPE ="ELEMITEM" \
HIDDEN ="NO" KEYTYPE ="{s_pk_yn}" LENGTH ="{s_length}" LEVEL ="0" NAME ="{v_column_name}" NULLABLE ="{s_nullable}" OCCURS ="0" OFFSET ="0" PHYSICALLENGTH ="{s_precision}" \
PHYSICALOFFSET ="0" PICTURETEXT ="" PRECISION ="{s_precision}" SCALE ="{s_scale}" USAGE_FLAGS =""/>\n')

if instDivCd != None and instDivCd != '':  # INSTANCE 필드 추가
    f.write(
        f'        <SOURCEFIELD BUSINESSNAME ="" DATATYPE ="varchar2" DESCRIPTION ="" FIELDNUMBER ="0" FIELDPROPERTY ="0" FIELDTYPE ="ELEMITEM" \
HIDDEN ="NO" KEYTYPE ="NOT A KEY" LENGTH ="0" LEVEL ="0" NAME ="INSTANCE" NULLABLE ="NOTNULL" OCCURS ="0" OFFSET ="0" PHYSICALLENGTH ="50" \
PHYSICALOFFSET ="0" PICTURETEXT ="" PRECISION ="50" SCALE ="0" USAGE_FLAGS =""/>\n')

st2 = """    </SOURCE>
    """
f.write(st2)

#####################################################
#       Target XML
#####################################################

if tgtDbms == 'BigQuery':
    xml_str = targetXmlGen.genBqTargetXmlStr(tgt_name, dsnm, tgtTbnm, dbms, instDivCd, rsltCol)
    f.write(xml_str)
else:
    targetXml = ET.parse(f'target/{tgtXml}')

    root = targetXml.getroot()

    for child in root.iter():
        if child.tag == "TARGET":
            child.attrib["NAME"] = f"{tgt_name}"
            for fld in child.iter():
                if fld.tag == "TARGETFIELD":
                    if fld.attrib["DATATYPE"] == "STRING":
                        fld.attrib["PRECISION"] = "80000"
                    if fld.attrib["DATATYPE"] == "NUMERIC" and fld.attrib[
                        "PRECISION"] > "28":  # precision이 28 이상 되면 double로 바뀌는 현상이 있으므로 28로 제한
                        fld.attrib["PRECISION"] = "28"

            xml_str = ET.tostring(child, encoding='utf-8')
            f.write(xml_str.decode('utf-8'))

            break

st3 = f"""    <MAPPING DESCRIPTION ="" ISVALID ="YES" NAME ="{mapp_name}" OBJECTVERSION ="1" VERSIONNUMBER ="1">
        <TRANSFORMATION DESCRIPTION ="" NAME ="SQ_{sysCd}_{srctbnm}" OBJECTVERSION ="1" REUSABLE ="NO" TYPE ="Source Qualifier" VERSIONNUMBER ="1">
"""
f.write(st3)

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

    f.write(
        f'            <TRANSFORMFIELD DATATYPE ="{s_data_type}" DEFAULTVALUE ="" DESCRIPTION ="" NAME ="{v_column_name}" PICTURETEXT ="" PORTTYPE ="INPUT/OUTPUT" \
PRECISION ="{s_precision}" SCALE ="{s_scale}"/>\n')

if instDivCd != None and instDivCd != '':  # INSTANCE 필드 추가
    f.write(
        f'            <TRANSFORMFIELD DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" NAME ="INSTANCE" PICTURETEXT ="" PORTTYPE ="INPUT/OUTPUT" \
PRECISION ="10" SCALE ="0"/>\n')

st4 = f"""            <TABLEATTRIBUTE NAME ="Sql Query" VALUE =""/>
            <TABLEATTRIBUTE NAME ="User Defined Join" VALUE =""/>
            <TABLEATTRIBUTE NAME ="Source Filter" VALUE =""/>
            <TABLEATTRIBUTE NAME ="Number Of Sorted Ports" VALUE ="0"/>
            <TABLEATTRIBUTE NAME ="Tracing Level" VALUE ="Normal"/>
            <TABLEATTRIBUTE NAME ="Select Distinct" VALUE ="NO"/>
            <TABLEATTRIBUTE NAME ="Is Partitionable" VALUE ="NO"/>
            <TABLEATTRIBUTE NAME ="Pre SQL" VALUE =""/>
            <TABLEATTRIBUTE NAME ="Post SQL" VALUE =""/>
            <TABLEATTRIBUTE NAME ="Output is deterministic" VALUE ="NO"/>
            <TABLEATTRIBUTE NAME ="Output is repeatable" VALUE ="Never"/>
        </TRANSFORMATION>
        <INSTANCE DESCRIPTION ="" NAME ="{tgt_name}1" TRANSFORMATION_NAME ="{tgt_name}" TRANSFORMATION_TYPE ="Target Definition" TYPE ="TARGET"/>
"""
f.write(st4)
if sysCd == 'GMES' and inst_name == 'GMESHQP':
    f.write(
        f"""        <INSTANCE DBDNAME ="{sysCd}" DESCRIPTION ="" NAME ="{srctbnm}" TRANSFORMATION_NAME ="{srctbnm}_GV" TRANSFORMATION_TYPE ="Source Definition" TYPE ="SOURCE">
              <TABLEATTRIBUTE NAME ="Source Table Name" VALUE ="{srctbnm}"/>
          </INSTANCE>""")
elif sysCd in ['GMES', 'GSFS', 'NBES', 'GFMS']:
    f.write(
        f"""        <INSTANCE DBDNAME ="{sysCd}" DESCRIPTION ="" NAME ="{srctbnm}" TRANSFORMATION_NAME ="{srctbnm}" TRANSFORMATION_TYPE ="Source Definition" TYPE ="SOURCE">
              <TABLEATTRIBUTE NAME ="Source Table Name" VALUE ="{srctbnm}"/>
          </INSTANCE>""")
else:
    f.write(
        f"""        <INSTANCE DBDNAME ="{sysCd}{postfix.replace('N', '')}" DESCRIPTION ="" NAME ="{srctbnm}" TRANSFORMATION_NAME ="{srctbnm}" TRANSFORMATION_TYPE ="Source Definition" TYPE ="SOURCE">
              <TABLEATTRIBUTE NAME ="Source Table Name" VALUE ="{srctbnm}"/>
          </INSTANCE>""")

f.write(f"""
        <INSTANCE DESCRIPTION ="" NAME ="SQ_{sysCd}_{srctbnm}" REUSABLE ="NO" TRANSFORMATION_NAME ="SQ_{sysCd}_{srctbnm}" TRANSFORMATION_TYPE ="Source Qualifier" TYPE ="TRANSFORMATION">
            <ASSOCIATED_SOURCE_INSTANCE NAME ="{srctbnm}"/>
        </INSTANCE>
        <INSTANCE DESCRIPTION ="" NAME ="EXP_LOAD_TIME" REUSABLE ="YES" TRANSFORMATION_NAME ="EXP_LOAD_TIME" TRANSFORMATION_TYPE ="Expression" TYPE ="TRANSFORMATION"/>
""")

#####################################################
#       connector : EXP -> Target
#####################################################
if tgtDbms == 'BigQuery':  # BQ에만 partition이 있음
    f.write(
        f"""        <CONNECTOR FROMFIELD ="o_PTT" FROMINSTANCE ="EXP_LOAD_TIME" FROMINSTANCETYPE ="Expression" TOFIELD ="P_PTT" TOINSTANCE ="{tgt_name}1" TOINSTANCETYPE ="Target Definition"/>
""")

f.write(
    f"""        <CONNECTOR FROMFIELD ="o_ETL_LOAD_TS" FROMINSTANCE ="EXP_LOAD_TIME" FROMINSTANCETYPE ="Expression" TOFIELD ="ETL_LOAD_TS" TOINSTANCE ="{tgt_name}1" TOINSTANCETYPE ="Target Definition"/>
""")

#####################################################
#       connector : SQ -> Target
#####################################################
for r, row in enumerate(rsltCol):
    v_column_name = row['column_name']
    f.write(
        f'        <CONNECTOR FROMFIELD ="{v_column_name}" FROMINSTANCE ="SQ_{sysCd}_{srctbnm}" FROMINSTANCETYPE ="Source Qualifier" \
TOFIELD ="{v_column_name}" TOINSTANCE ="{tgt_name}1" TOINSTANCETYPE ="Target Definition"/>\n')

if instDivCd != None and instDivCd != '':  # INSTANCE 필드 추가
    f.write(
        f'        <CONNECTOR FROMFIELD ="INSTANCE" FROMINSTANCE ="SQ_{sysCd}_{srctbnm}" FROMINSTANCETYPE ="Source Qualifier" \
TOFIELD ="INSTANCE" TOINSTANCE ="{tgt_name}1" TOINSTANCETYPE ="Target Definition"/>\n')

#####################################################
#       connector : Source -> SQ
#####################################################
for r, row in enumerate(rsltCol):
    v_column_name = row['column_name']
    # v_data_type = row['DATA_TYPE']

    # if v_data_type in ('VARCHAR2','VARCHAR'):
    # s_attr1 = v_column_name #for EXP_LOAD_TIME.ATTRIBUTE01 connector
    s_attr1 = v_column_name  # for EXP_LOAD_TIME.ATTRIBUTE01 connector

    f.write(
        f'        <CONNECTOR FROMFIELD ="{v_column_name}" FROMINSTANCE ="{srctbnm}" FROMINSTANCETYPE ="Source Definition" TOFIELD ="{v_column_name}" \
TOINSTANCE ="SQ_{sysCd}_{srctbnm}" TOINSTANCETYPE ="Source Qualifier"/>\n')

if instDivCd != None and instDivCd != '':  # INSTANCE 필드 추가
    f.write(
        f'        <CONNECTOR FROMFIELD ="INSTANCE" FROMINSTANCE ="{srctbnm}" FROMINSTANCETYPE ="Source Definition" TOFIELD ="INSTANCE" \
TOINSTANCE ="SQ_{sysCd}_{srctbnm}" TOINSTANCETYPE ="Source Qualifier"/>\n')

#####################################################
#       connector : SQ -> EXP
#####################################################
f.write(
    f'        <CONNECTOR FROMFIELD ="{s_attr1}" FROMINSTANCE ="SQ_{sysCd}_{srctbnm}" FROMINSTANCETYPE ="Source Qualifier" TOFIELD ="ATTRIBUTE01" \
TOINSTANCE ="EXP_LOAD_TIME" TOINSTANCETYPE ="Expression"/>\n')
f.write(f'        <TARGETLOADORDER ORDER ="1" TARGETINSTANCE ="{tgt_name}1"/>\n')

f.write(
    f"""        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$Table_D" PRECISION ="300" SCALE ="0" USERDEFINED ="YES"/>
        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$P_BASE_DATE" PRECISION ="10" SCALE ="0" USERDEFINED ="YES"/>
        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$P_BF1_BASE_DATE" PRECISION ="10" SCALE ="0" USERDEFINED ="YES"/>
        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$DataSet" PRECISION ="20" SCALE ="0" USERDEFINED ="YES"/>
        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$Instance_Name" PRECISION ="30" SCALE ="0" USERDEFINED ="YES"/>
        <MAPPINGVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="" ISEXPRESSIONVARIABLE ="NO" ISPARAM ="YES" NAME ="$$P_BF1_BASE_MONTH" PRECISION ="10" SCALE ="0" USERDEFINED ="YES"/>
""")

st5 = f"""        <ERPINFO/>
    </MAPPING>
"""
f.write(st5)

#####################################################
#       SESSION XML
#####################################################
### get sql query
if dbms != 'ORACLE':
    sql_query = "SELECT "
else:
    if index_nm == None:
        # if hint_nm == None:
        #     sql_query = "SELECT "
        # else:
        #     sql_query = f"SELECT /*+ {hint_nm} */ "
        sql_query = "SELECT "
    else:
        sql_query = f"SELECT /*+ INDEX_RS({srctbnm} {index_nm}) */ "

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
        sql_query = sql_query + ","

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
    sql_query = sql_query + f",'{instDivCd}' AS INSTANCE"

if dbms in ['MYSQL', 'MARIADB']:
    sql_query = sql_query + f" FROM " + f"{ownernm}.{srctbnm}".lower()
else:
    sql_query = sql_query + f" FROM {ownernm}.{srctbnm}"

if dbms == 'MS SQL SERVER':
    if index_nm == None:
        sql_query = sql_query + " WITH (NOLOCK)"
    else:
        sql_query = sql_query + " WITH (INDEX(" + f"{index_nm}), NOLOCK)"
elif dbms in ['MYSQL', 'MARIADB']:
    if index_nm != None:
        sql_query = sql_query + " USE INDEX " + f"({index_nm})"
elif dbms == 'ORACLE':
    if part_nm != None:
        sql_query = sql_query + f" PARTITION ({part_nm}) "

# print(m_filters)
if init_mod_flag == 'I':
    src_filter = ""
    if addCondition_val != None:
        src_filter = src_filter + f"AND {addCondition_val}"

else:
    # 변경 적재 조건
    # if m_filter == "":
    if len(m_filters) == 0:
        src_filter = ""
    else:
        src_filter = "AND ( "
        for r, m_filter_mbr in enumerate(m_filters):
            m_filter = m_filter_mbr[0]
            m_filter_datatype = m_filter_mbr[1]

            if r > 0:
                src_filter = src_filter + " OR "

            if m_filter_datatype in ("DATE", "TIMESTAMP", "TIMESTAMP(6)", "DATETIME", "DATETIME2", "TIMESTAMP WITHOUT TIME ZONE"):
                if dbms in ['ORACLE','POSTGRESQL']: # POSTGRESQL 추가 20240411 jsoh
                    src_filter = src_filter + f" {m_filter} &gt;= TO_DATE(&apos;$$P_BF1_BASE_DATE&apos;, &apos;YYYYMMDD&apos;) AND {m_filter} &lt; TO_DATE(&apos;$$P_BASE_DATE&apos;, &apos;YYYYMMDD&apos;) + 1"
                elif dbms in ['MYSQL', 'MARIADB']:
                    src_filter = src_filter + f" {m_filter} &gt;= STR_TO_DATE(&apos;$$P_BF1_BASE_DATE&apos;, &apos;%Y%m%d&apos;) AND {m_filter} &lt; DATE_ADD(STR_TO_DATE(&apos;$$P_BASE_DATE&apos;, &apos;%Y%m%d&apos;), INTERVAL 1 DAY)"
                elif dbms == 'MS SQL SERVER':
                    src_filter = src_filter + f" {m_filter} &gt;= CONVERT(DATETIME, &apos;$$P_BF1_BASE_DATE&apos;, 112) AND {m_filter} &lt; DATEADD(day, 1, CONVERT(DATETIME, &apos;$$P_BASE_DATE&apos;, 112))"
                elif dbms == 'Vertica':
                    src_filter = src_filter + f" {m_filter} &gt;= TO_TIMESTAMP(&apos;$$P_BF1_BASE_DATE&apos;, &apos;YYYYMMDD&apos;) AND {m_filter} &lt; TIMESTAMPADD(day, 1, TO_TIMESTAMP(&apos;$$P_BASE_DATE&apos;, &apos;YYYYMMDD&apos;))"
                elif dbms == 'DB2 UDB':  # 분할 초기적재 DB2 TIMESTAMP타입 추가 (이은송, 23/11/07)
                    src_filter = src_filter + f" {m_filter} &gt;= TIMESTAMP(SUBSTR(&apos;$$P_BF1_BASE_DATE&apos;,1,4)||&apos;-&apos;||SUBSTR(&apos;$$P_BF1_BASE_DATE&apos;,5,2)||&apos;-&apos;||SUBSTR(&apos;$$P_BF1_BASE_DATE&apos;,7,2)||&apos; 00:00:00.000&apos;) AND {m_filter} &lt; TIMESTAMP(SUBSTR(&apos;$$P_BASE_DATE&apos;,1,4)||&apos;-&apos;||SUBSTR(&apos;$$P_BASE_DATE&apos;,5,2)||&apos;-&apos;||SUBSTR(&apos;$$P_BASE_DATE&apos;,7,2)||&apos; 00:00:00.000&apos;) + 1 DAY"
            elif m_filter_datatype in ("VARCHAR2", "VARCHAR", "NVARCHAR", "NVARCHAR2", "CHAR", "CHARACTER VARYING"):
                src_filter = src_filter + f" {m_filter} &gt;= &apos;$$P_BF1_BASE_DATE&apos; AND {m_filter} &lt; &apos;$$P_BASE_DATE999999&apos;"

        src_filter = src_filter + ")"

# 세션 분리 조건
if sess_div_seq != None:
    if sess_div_from_val == "N" and sess_div_to_val == "N":
        src_filter = src_filter + f" AND {sess_div_col} is null"
    elif sess_div_from_val == "N":
        if sess_div_col_datatype in ("DATE", "TIMESTAMP", "TIMESTAMP(6)", "DATETIME", "DATETIME2", "TIMESTAMP WITHOUT TIME ZONE"):
            if dbms in ['ORACLE','POSTGRESQL']: # POSTGRESQL 추가 20240411 jsoh
                src_filter = src_filter + f" AND {sess_div_col} &lt; TO_DATE(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms in ['MYSQL', 'MARIADB']:
                src_filter = src_filter + f" AND {sess_div_col} &lt; STR_TO_DATE(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'MS SQL SERVER':
                src_filter = src_filter + f" AND {sess_div_col} &lt; CONVERT(DATETIME, &apos;{sess_div_to_val}&apos;, {sess_div_col_date_fmt})"
            elif dbms == 'Vertica':
                src_filter = src_filter + f" AND {sess_div_col} &lt; TO_TIMESTAMP(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'DB2 UDB' and len(sess_div_to_val) == 8:  # 분할 초기적재 DB2 TIMESTAMP타입 추가 (이은송, 23/11/07)
                src_filter = src_filter + f" AND {sess_div_col} &lt; TIMESTAMP(&apos;{sess_div_to_val[:4]}-{sess_div_to_val[4:6]}-{sess_div_to_val[6:8]} 00:00:00.000&apos;)"
        elif sess_div_col_datatype in ("VARCHAR2", "CHAR", "VARCHAR", "NVARCHAR", "NVARCHAR2", "CHARACTER VARYING"): # POSTGRESQL 타입추가 (이은소이, 2024/12/16)
            src_filter = src_filter + f" AND {sess_div_col} &lt; &apos;{sess_div_to_val}&apos;"
        elif sess_div_col_datatype in (
                "NUMBER", "INTEGER", "INT", "TINYINT", "BIGINT", "SMALLINT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE",
        "BINARY_DOUBLE", "BINARY_FLOAT", "MONEY"):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
            src_filter = src_filter + f" AND {sess_div_col} &lt; {sess_div_to_val}"
    elif sess_div_to_val == "N":
        if sess_div_col_datatype in ("DATE", "TIMESTAMP", "TIMESTAMP(6)", "DATETIME", "DATETIME2", "TIMESTAMP WITHOUT TIME ZONE"):
            if dbms in ['ORACLE','POSTGRESQL']: # POSTGRESQL 추가 20240411 jsoh
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TO_DATE(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms in ['MYSQL', 'MARIADB']:
                src_filter = src_filter + f" AND {sess_div_col} &gt;= STR_TO_DATE(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'MS SQL SERVER':
                src_filter = src_filter + f" AND {sess_div_col} &gt;= CONVERT(DATETIME, &apos;{sess_div_from_val}&apos;, {sess_div_col_date_fmt})"
            elif dbms == 'Vertica':
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TO_TIMESTAMP(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'DB2 UDB' and len(sess_div_from_val) == 8:  # 분할 초기적재 DB2 TIMESTAMP타입 추가 (이은송, 23/11/07)
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TIMESTAMP(&apos;{sess_div_from_val[:4]}-{sess_div_from_val[4:6]}-{sess_div_from_val[6:8]} 00:00:00.000&apos;)"
        elif sess_div_col_datatype in ("VARCHAR2", "CHAR", "VARCHAR", "NVARCHAR", "NVARCHAR2", "CHARACTER VARYING"): # POSTGRESQL 타입추가 (이은소이, 2024/12/16)
            src_filter = src_filter + f" AND {sess_div_col} &gt;= &apos;{sess_div_from_val}&apos;"
        elif sess_div_col_datatype in (
                "NUMBER", "INTEGER", "INT", "TINYINT", "BIGINT", "SMALLINT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE",
        "BINARY_DOUBLE", "BINARY_FLOAT", "MONEY"):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
            src_filter = src_filter + f" AND {sess_div_col} &gt;= {sess_div_from_val}"
    else:
        if sess_div_col_datatype in ("DATE", "TIMESTAMP", "TIMESTAMP(6)", "DATETIME", "DATETIME2", "TIMESTAMP WITHOUT TIME ZONE"):
            if dbms in ['ORACLE','POSTGRESQL']: # POSTGRESQL 추가 20240411 jsoh
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TO_DATE(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;) AND {sess_div_col} &lt; TO_DATE(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms in ['MYSQL', 'MARIADB']:
                src_filter = src_filter + f" AND {sess_div_col} &gt;= STR_TO_DATE(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;) AND {sess_div_col} &lt; STR_TO_DATE(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'MS SQL SERVER':
                src_filter = src_filter + f" AND {sess_div_col} &gt;= CONVERT(DATETIME, &apos;{sess_div_from_val}&apos;, {sess_div_col_date_fmt}) AND {sess_div_col} &lt; CONVERT(DATETIME, &apos;{sess_div_to_val}&apos;, {sess_div_col_date_fmt})"
            elif dbms == 'Vertica':
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TO_TIMESTAMP(&apos;{sess_div_from_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;) AND {sess_div_col} &lt; TO_TIMESTAMP(&apos;{sess_div_to_val}&apos;, &apos;{sess_div_col_date_fmt}&apos;)"
            elif dbms == 'DB2 UDB' and len(sess_div_from_val) == 8 and len(
                    sess_div_to_val) == 8:  # 분할 초기적재 DB2 TIMESTAMP타입 추가 (이은송, 23/11/07)
                src_filter = src_filter + f" AND {sess_div_col} &gt;= TIMESTAMP(&apos;{sess_div_from_val[:4]}-{sess_div_from_val[4:6]}-{sess_div_from_val[6:8]} 00:00:00.000&apos;) AND {sess_div_col} &lt; TIMESTAMP(&apos;{sess_div_to_val[:4]}-{sess_div_to_val[4:6]}-{sess_div_to_val[6:8]} 00:00:00.000&apos;)"
        elif sess_div_col_datatype in ("VARCHAR2", "CHAR", "VARCHAR", "NVARCHAR", "NVARCHAR2", "CHARACTER VARYING"): # POSTGRESQL 타입추가 (이은소이, 2024/12/16)
            src_filter = src_filter + f" AND {sess_div_col} &gt;= &apos;{sess_div_from_val}&apos; AND {sess_div_col} &lt; &apos;{sess_div_to_val}&apos;"
        elif sess_div_col_datatype in (
                "NUMBER", "INTEGER", "INT", "TINYINT", "BIGINT", "SMALLINT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE",
        "BINARY_DOUBLE", "BINARY_FLOAT", "MONEY"):  # PUSI DB에 BINARY_DOUBLE 타입 존재하여 추가 (한병학, '21/10/07)
            src_filter = src_filter + f" AND {sess_div_col} &gt;= {sess_div_from_val} AND {sess_div_col} &lt; {sess_div_to_val}"

if src_filter != "":
    sql_query = sql_query + f" WHERE 1=1 {src_filter}"

#DB2는 SELECT절 마지막에 WITH UR 붙이기 ('24/09/23, 이은송)
if dbms == 'DB2 UDB':
    sql_query = sql_query + " WITH UR"

### get pre_sql
if init_mod_flag == 'I':
    if sess_div_seq != None:  # session 분리
        write_mod = 'Write append'
    else:
        write_mod = 'Write truncate'
    pre_sql = ""
    pre_sql_conf = ""
else:
    write_mod = 'Write append'
    if tgtDbms == 'BigQuery':

        pre_sql_add = ""
        if instDivCd != None and instDivCd != '':  # INSTANCE 컬럼 추가 (2024.11.11)
            pre_sql_add = f" AND INSTANCE = '$$Instance_Name'"

        pre_sql = f"DELETE FROM {dsnm}.{tgtTbnm} WHERE P_PTT = CURRENT_DATE(\'Asia/Seoul\'){pre_sql_add}"  # P_PTT between PARSE_DATE (&apos;%Y%m%d&apos;,&apos;$$P_BF1_BASE_DATE&apos;) AND PARSE_DATE(&apos;%Y%m%d&apos;,&apos;$$P_BASE_DATE&apos;)'
        pre_sql_conf = 'UseLegacySQL:False'
    else:
        pre_sql = ""
        pre_sql_conf = ""

f.write(
    f"""    <SESSION DESCRIPTION ="" ISVALID ="YES" MAPPINGNAME ="{mapp_name}" NAME ="{sess_name}" REUSABLE ="YES" SORTORDER ="Binary" VERSIONNUMBER ="1">
""")

if tgtDbms == 'BigQuery':
    f.write(
        f"""        <SESSTRANSFORMATIONINST ISREPARTITIONPOINT ="YES" PARTITIONTYPE ="PASS THROUGH" PIPELINE ="1" SINSTANCENAME ="{tgt_name}1" STAGE ="1" TRANSFORMATIONNAME ="{tgt_name}1" TRANSFORMATIONTYPE ="Target Definition"/>
""")
else:
    f.write(
        f"""        <SESSTRANSFORMATIONINST ISREPARTITIONPOINT ="YES" PARTITIONTYPE ="PASS THROUGH" PIPELINE ="1" SINSTANCENAME ="{tgt_name}1" STAGE ="1" TRANSFORMATIONNAME ="{tgt_name}1" TRANSFORMATIONTYPE ="Target Definition">
            <ATTRIBUTE NAME ="Table Name Prefix" VALUE ="{dsnm}"/>
          <ATTRIBUTE NAME ="Target Table Name" VALUE ="{tgtTbnm}"/>
        </SESSTRANSFORMATIONINST>
""")

f.write(
    f"""        <SESSTRANSFORMATIONINST ISREPARTITIONPOINT ="NO" PIPELINE ="0" SINSTANCENAME ="{srctbnm}" STAGE ="0" TRANSFORMATIONNAME ="{srctbnm}" TRANSFORMATIONTYPE ="Source Definition">
            <ATTRIBUTE NAME ="Owner Name" VALUE ="{ownernm}"/>
        </SESSTRANSFORMATIONINST>
        <SESSTRANSFORMATIONINST ISREPARTITIONPOINT ="YES" PARTITIONTYPE ="PASS THROUGH" PIPELINE ="1" SINSTANCENAME ="SQ_{sysCd}_{srctbnm}" STAGE ="2" TRANSFORMATIONNAME ="SQ_{sysCd}_{srctbnm}" TRANSFORMATIONTYPE ="Source Qualifier">
          <ATTRIBUTE NAME ="Sql Query" VALUE ="{sql_query}"/>
        </SESSTRANSFORMATIONINST>
        <SESSTRANSFORMATIONINST ISREPARTITIONPOINT ="NO" PIPELINE ="1" SINSTANCENAME ="EXP_LOAD_TIME" STAGE ="2" TRANSFORMATIONNAME ="EXP_LOAD_TIME" TRANSFORMATIONTYPE ="Expression">
            <PARTITION DESCRIPTION ="" NAME ="파티션 #1"/>
        </SESSTRANSFORMATIONINST>
        <CONFIGREFERENCE REFOBJECTNAME ="default_session_config" TYPE ="Session config">
            <ATTRIBUTE NAME ="Default buffer block size" VALUE ="64000000"/>
        </CONFIGREFERENCE>
""")

# session 분리할 경우에는 post procedure 수동 실행 & RDB일 경우 post procedure 없음
if sess_div_seq == None and tgtDbms == 'BigQuery':
    f.write(
        f"""        <SESSIONCOMPONENT REFOBJECTNAME ="cmd_SP_Merge" REUSABLE ="YES" TYPE ="Post-session success command"/>
""")

# OBS일 경우에는 터널링 미리 실행 (리스트를 myMap.py에서 관리)
# if connnm in ['OBS_GP', 'OBS_US', 'OBS2', 'OBS_SR', 'KMIM']:
if connnm in tunnelConnectList:
    f.write(
        f"""        <SESSIONCOMPONENT REFOBJECTNAME ="cmd_{connnm}_Tunnel" REUSABLE ="YES" TYPE ="Pre-session command"/>
""")

if tgtDbms == 'BigQuery':
    st6 = f"""        <SESSIONEXTENSION COMPONENTVERSION ="1000000" NAME ="bigquery Writer" SINSTANCENAME ="{tgt_name}1" SUBTYPE ="bigquery Writer" TRANSFORMATIONTYPE ="Target Definition" TYPE ="WRITER">
            <CONNECTIONREFERENCE CNXREFNAME ="bigquery" COMPONENTVERSION ="1000000" CONNECTIONNAME ="bigquery" CONNECTIONNUMBER ="1" CONNECTIONSUBTYPE ="bigquery" CONNECTIONTYPE ="Application" VARIABLE =""/>
            <ATTRIBUTE NAME ="UpdateMode" VALUE ="Update As Update"/>
            <ATTRIBUTE NAME ="Target Dataset ID" VALUE ="{dsnm}"/>
            <ATTRIBUTE NAME ="Target Table Name" VALUE ="{tgtTbnm}"/>
            <ATTRIBUTE NAME ="Create Disposition" VALUE ="Create never"/>
            <ATTRIBUTE NAME ="Write Disposition" VALUE ="{write_mod}"/>
            <ATTRIBUTE NAME ="Write Mode" VALUE ="Bulk"/>
            <ATTRIBUTE NAME ="Streaming Template Table Suffix" VALUE =""/>
            <ATTRIBUTE NAME ="Rows per Streaming Request" VALUE ="500"/>
            <ATTRIBUTE NAME ="Staging File Name" VALUE =""/>
            <ATTRIBUTE NAME ="Data format of the staging file" VALUE ="JSON (Newline Delimited)"/>
            <ATTRIBUTE NAME ="Persist Staging File After Loading" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Enable Staging File Compression" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Job Poll Interval In Seconds" VALUE ="10"/>
            <ATTRIBUTE NAME ="Number of Threads for Uploading Staging File" VALUE ="1"/>
            <ATTRIBUTE NAME ="Allow Quoted Newlines" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Field Delimiter" VALUE =","/>
            <ATTRIBUTE NAME ="Allow Jagged Rows" VALUE ="NO"/>
            <ATTRIBUTE NAME ="pre SQL" VALUE ="{pre_sql}"/>
            <ATTRIBUTE NAME ="post SQL" VALUE =""/>
            <ATTRIBUTE NAME ="pre SQL Configuration" VALUE ="{pre_sql_conf}"/>
            <ATTRIBUTE NAME ="post SQL Configuration" VALUE =""/>
            <ATTRIBUTE NAME ="Quote Char" VALUE ="&quot;"/>
            <ATTRIBUTE NAME ="INSERT" VALUE ="NO"/>
            <ATTRIBUTE NAME ="DELETE" VALUE ="NO"/>
            <ATTRIBUTE NAME ="UPDATE" VALUE ="None"/>
            <ATTRIBUTE NAME ="Success File Directory" VALUE =""/>
            <ATTRIBUTE NAME ="Error File Directory" VALUE =""/>
            <ATTRIBUTE NAME ="Spark Mode" VALUE ="Generic"/>
            <ATTRIBUTE NAME ="Local Stage File Directory" VALUE =""/>
        </SESSIONEXTENSION>
"""
else:
    st6 = f"""        <SESSIONEXTENSION NAME ="Relational Writer" SINSTANCENAME ="{tgt_name}1" SUBTYPE ="Relational Writer" TRANSFORMATIONTYPE ="Target Definition" TYPE ="WRITER">
            <CONNECTIONREFERENCE CNXREFNAME ="DB Connection" CONNECTIONNAME ="MYSQL_P" CONNECTIONNUMBER ="1" CONNECTIONSUBTYPE ="ODBC" CONNECTIONTYPE ="Relational" VARIABLE =""/>
            <ATTRIBUTE NAME ="Target load type" VALUE ="Bulk"/>
            <ATTRIBUTE NAME ="Insert" VALUE ="YES"/>
            <ATTRIBUTE NAME ="Update as Update" VALUE ="YES"/>
            <ATTRIBUTE NAME ="Update as Insert" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Update else Insert" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Delete" VALUE ="YES"/>
            <ATTRIBUTE NAME ="Truncate target table option" VALUE ="NO"/>
            <ATTRIBUTE NAME ="Reject file directory" VALUE ="$PMBadFileDir&#x5c;"/>
            <ATTRIBUTE NAME ="Reject filename" VALUE ="{sysCd}_{srctbnm}1.bad"/>
        </SESSIONEXTENSION>
"""

f.write(st6)

st7 = f"""        <SESSIONEXTENSION DSQINSTNAME ="SQ_{sysCd}_{srctbnm}" DSQINSTTYPE ="Source Qualifier" NAME ="Relational Reader" SINSTANCENAME ="{srctbnm}" SUBTYPE ="Relational Reader" TRANSFORMATIONTYPE ="Source Definition" TYPE ="READER"/>
        <SESSIONEXTENSION NAME ="Relational Reader" SINSTANCENAME ="SQ_{sysCd}_{srctbnm}" SUBTYPE ="Relational Reader" TRANSFORMATIONTYPE ="Source Qualifier" TYPE ="READER">
            <CONNECTIONREFERENCE CNXREFNAME ="DB Connection" CONNECTIONNAME ="{connnm}" CONNECTIONNUMBER ="1" CONNECTIONSUBTYPE ="{connSubType}" CONNECTIONTYPE ="Relational" VARIABLE =""/>
        </SESSIONEXTENSION>
        <ATTRIBUTE NAME ="General Options" VALUE =""/>
        <ATTRIBUTE NAME ="Write Backward Compatible Session Log File" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Session Log File Name" VALUE ="{sess_name}.log"/>
        <ATTRIBUTE NAME ="Session Log File directory" VALUE ="$PMSessionLogDir&#x5c;"/>
        <ATTRIBUTE NAME ="Parameter Filename" VALUE =""/>
        <ATTRIBUTE NAME ="Enable Test Load" VALUE ="NO"/>
        <ATTRIBUTE NAME ="$Source connection value" VALUE =""/>
        <ATTRIBUTE NAME ="$Target connection value" VALUE =""/>
        <ATTRIBUTE NAME ="Treat source rows as" VALUE ="Insert"/>
        <ATTRIBUTE NAME ="Commit Type" VALUE ="Target"/>
        <ATTRIBUTE NAME ="Commit Interval" VALUE ="10000"/>
        <ATTRIBUTE NAME ="Commit On End Of File" VALUE ="YES"/>
        <ATTRIBUTE NAME ="Rollback Transactions on Errors" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Recovery Strategy" VALUE ="Fail task and continue workflow"/>
        <ATTRIBUTE NAME ="Java Classpath" VALUE =""/>
        <ATTRIBUTE NAME ="Performance" VALUE =""/>
        <ATTRIBUTE NAME ="DTM buffer size" VALUE ="Auto"/>
        <ATTRIBUTE NAME ="Collect performance data" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Write performance data to repository" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Incremental Aggregation" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Enable high precision" VALUE ="YES"/>
        <ATTRIBUTE NAME ="Session retry on deadlock" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Pushdown Optimization" VALUE ="None"/>
        <ATTRIBUTE NAME ="Allow Temporary View for Pushdown" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Allow Temporary Sequence for Pushdown" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Allow Pushdown for User Incompatible Connections" VALUE ="NO"/>
    </SESSION>
"""

f.write(st7)

f.close()
