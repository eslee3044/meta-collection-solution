import argparse
import psycopg2
from psycopg2.extras import DictCursor
import os

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-p", "--postfix", required=False, help="INSTANCE_NAME - multi instance일 경우 only (ex) APNGSFSP, LGNBHP ...")
ap.add_argument("-d", "--directory", required=False, help="프로시저 스크립트파일 생성 디렉토리 지정")
args = vars(ap.parse_args())

tbnm = args["table"]
sysCd = args["system"]
postfix = args["postfix"]
addDir = args["directory"]

# Postgres Connection 연결
conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

#####################################################
#				Get Table Info
#####################################################
sqlSelTab = f"""
SELECT system_cd
	, postfix
	, owner
	, table_name
	, database_name
	, etl_conn_div_cd
	, etl_conn_nm
	, tgt_ds_cd
	, tgt_table_name
	, tgt_database_name
	, instance_div_cd
	, sess_name_rule
	, mapp_name_rule
	, tgt_name_rule
	, partition_col_modifiable_yn
FROM eapet.tb_meta_tables_ext
WHERE system_cd = '{sysCd}'
AND UPPER(table_name) = '{tbnm}'
AND postfix = '{postfix}'
"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()
for rowTab in rsltTab:
    instDivCd = rowTab['instance_div_cd']
    srcTbnm = rowTab['table_name']
    tgtTbnm = rowTab['tgt_table_name']
    dsnm = rowTab['tgt_ds_cd']
    part_mod_yn = rowTab['partition_col_modifiable_yn']

    break;  # 한 row만 필요함

dsnmBd = dsnm[-4:]  # 'ST_' 제외

# Multiple Instance YN
if instDivCd != None and instDivCd != '':
    mult_inst_flag = "Y"
else:
    mult_inst_flag = "N"

#####################################################
#				Get Column Info
#####################################################
# multi instance의 경우 mapping을 공유하기 위해 instance들의 합집합을 사용한다.
# mapping 공유할 시스템의 경우 합집합을 사용

sqlSelCol = f"""
SELECT system_cd
	, table_name
	, column_name
	, MAX(data_type) data_type
	, MAX(pk_yn) pk_yn
	, MAX(partition_key_yn) partition_key_yn
	, coalesce(MAX(comments), '') comments
	, MAX(column_id) column_id
FROM eapet.tb_meta_columns_ext
WHERE system_cd = '{sysCd}'
AND UPPER(table_name) = '{tbnm}'"""

if sysCd not in ['GMES','NBES','GSFS','GFMS']:                # 매핑 공유 시스템들이 아닌 경우
    sqlSelCol += f"""AND POSTFIX = '{postfix}'"""

sqlSelCol += f"""GROUP BY system_cd, table_name, column_name
UNION ALL
-- multi instance의 경우 INSTANCE 컬럼 추가
SELECT '{sysCd}' system_cd 
	, '{tbnm}' table_name
	, 'INSTANCE' column_name
	, '' data_type
	, 'Y' pk_yn
	, 'N' partition_key_yn
	, 'INSTANCE 구분 값' comments
	, 0 column_id
WHERE '{mult_inst_flag}' = 'Y'
ORDER BY system_cd, table_name, column_id
"""

curs.execute(sqlSelCol)
rsltAllCols = curs.fetchall()

rsltKeyCols = []
rsltNonKeyCols = []
rsltPttCols = []
for row in rsltAllCols:
    # print(row)
    if row["pk_yn"] == "Y":  # pk_yn
        rsltKeyCols.append(row)
    else:
        rsltNonKeyCols.append(row)

    if row["partition_key_yn"] == "Y":
        rsltPttCols.append(row)

# partition information
if len(rsltPttCols) > 0:
    part_yn = "Y"  # 파티션 여부
    dt_col_nm = rsltPttCols[0]['column_name']  # 파티션 DATE 컬럼명
    if rsltPttCols[0]['data_type'] in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2', 'TIMESTAMP WITHOUT TIME ZONE'): # DATETIME2 추가(20211118,한병학)
        dt_col_date_yn = "Y"  # 파티션 DATE 컬럼명이 DATE type인지 여부(Y:DATE, N:VARCHAR)
    else:
        dt_col_date_yn = "N"
else:
    part_yn = "N"

#  (20/12/15, 김현진c)
sptbnm = ''
if sysCd == 'GMES' and postfix == 'GMESHQP':
	sptbnm = srcTbnm + '_GV'
elif sysCd == 'GMES' or postfix == 'N':
	sptbnm = srcTbnm
else:
	sptbnm = tgtTbnm

######## 스크립트 생성 시작 ########
# 프로시저 파일 생성 후 print로 생성 파일 정보를 보여주기 위해서 변수로 설정 - (이은송C, 2023.12.15)
foldernm = 'merge'
filenm = f'SP_MRG_{sptbnm}(TrunIns).sql'

# 디렉토리 추가 (2024/06/27, 이은송C)
if addDir != None:
    addDir = addDir + '/'
    folder_path = os.path.join(os.getcwd(), f'{foldernm}/{addDir}')
    # print(f"folder_path : {folder_path}")
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
        except Exception as e:
            print(f"폴더 생성 중 오류 발생: {e}")
else:
    addDir = ''

#f = open(f'merge/SP_MRG_{sptbnm}(TrunIns).sql', 'w', encoding='utf-8')
f = open(f'{foldernm}/{addDir}{filenm}', 'w', encoding='utf-8')

f.write(f"CREATE OR REPLACE PROCEDURE ST_{dsnmBd}.SP_MRG_{sptbnm} (IN p_base_date DATE, IN p_instance STRING)\n")
f.write("BEGIN\n\n")

#  (24/04/04, 이은송c) GMESHQP인 경우 다이나믹 쿼리를 사용하지 않으므로, TGT_TABLE_NAME을 사용 (SP명은 GV까지만)
if postfix == 'GMESHQP':
    sptbnm = tgtTbnm

# L0 Target Merge Statement

f.write(f"""\t-- L0 Target merge statement
""")
if mult_inst_flag == 'Y':
    f.write(f"""\tDELETE L0_{dsnmBd}.{sptbnm} T 
\tWHERE T.INSTANCE = p_instance;

""")
else:
    f.write(f"""\tTRUNCATE TABLE L0_{dsnmBd}.{sptbnm};

""")

f.write(f"""\tINSERT INTO L0_{dsnmBd}.{sptbnm}(
""")

if part_yn == 'Y':
    f.write("\t\tp_ptt\n\t\t,")
else:
    f.write("\t\t")

# f.write("\t\tp_ptt\n\t\t,")

f.write("ETL_LOAD_TS\n")

for r, row in enumerate(rsltAllCols):
    f.write(f"\t\t,{row['column_name']}\n")

f.write("\t)\n")

f.write("""\tSELECT
""")

if part_yn == 'Y':
    if dt_col_date_yn == 'Y':
        f.write(f"\t\tDATE({dt_col_nm})\n\t\t,")
    else:
        f.write(f'\t\tPARSE_DATE("%Y%m%d", SUBSTR({dt_col_nm},1,8))\n\t\t,')
else:
    f.write("\t\t")
# f.write("\t\t'9999-12-31'\n\t\t,")

f.write("CURRENT_TIMESTAMP()\n")

for r, row in enumerate(rsltAllCols):
    f.write(f"\t\t,{row['column_name']}\n")

f.write(f"\tFROM ST_{dsnmBd}.{sptbnm}\n")

# 파티션 유무에 관계없이 WHERE p_ptt >= p_base_date 구문은 존재하는 것으로 변경 (김현진 책임, 20/08/11)
f.write(f"\tWHERE p_ptt >= p_base_date\n")

if part_yn == 'Y' and part_mod_yn == 'N':
    # CASE1: 날짜컬럼 & 멀티 인스턴스
    if dt_col_date_yn == 'Y' and mult_inst_flag == 'Y':
        f.write(f"\tAND INSTANCE = p_instance\n")

    # CASE3: 문자열컬럼 & 멀티 인스턴스
    elif dt_col_date_yn == 'N' and mult_inst_flag == 'Y':
        f.write(f"\tAND INSTANCE = p_instance\n")

f.write("\t;\n\nEND;\n\n")

f.close()
# 작업완료 표시 - (이은송C, 2023.12.15)
print(f"{foldernm}/{addDir} 폴더 하위 {filenm}가 생성되었습니다.")
