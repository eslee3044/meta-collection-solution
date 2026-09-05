import argparse
import psycopg2
from psycopg2.extras import DictCursor
import os

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-p", "--postfix", required=False, help="TABLE POSTFIX ex) GP, US, GMESCRP ")
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
AND table_name = '{tbnm}'
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
if instDivCd != None:
    mult_inst_flag = "Y"
else:
    mult_inst_flag = "N"

#####################################################
#				Get Column Info
#####################################################
# multi instance의 경우 mapping을 공유하기 위해 instance들의 합집합을 사용한다.
sqlSelCol = f"""
SELECT system_cd
	, table_name
	, column_name
	, MAX(data_type) data_type
	, MAX(pk_yn) pk_yn
	, MAX(partition_key_yn) partition_key_yn
	, coalesce(MAX(comments), '') comments
	, MAX(column_id) AS column_id
FROM eapet.tb_meta_columns_ext
WHERE system_cd = '{sysCd}'
AND table_name = '{tbnm}'"""

if sysCd not in ['GMES', 'NBES', 'GSFS', 'GFMS']:  # 매핑 공유 시스템들이 아닌 경우
    sqlSelCol += f"""AND postfix = '{postfix}'"""

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
	, 99999 AS column_id
WHERE '{mult_inst_flag}' = 'Y'
ORDER BY column_id
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
    ptt_col_nm = rsltPttCols[0]["column_name"]  # 파티션 컬럼명
    ptt_col_data_type = rsltPttCols[0]["data_type"]  # 파티션 컬럼 데이터타입
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

# 프로시저 파일 생성 후 print로 생성 파일 정보를 보여주기 위해서 변수로 설정 - (이은송C, 2023.12.15)
foldernm = 'merge'
filenm = f'SP_MRG_{sptbnm}(Merge).sql'

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

#f = open(f'merge/SP_MRG_{sptbnm}(Merge).sql', 'w', encoding='utf-8')
f = open(f'{foldernm}/{addDir}{filenm}', 'w', encoding='utf-8')
f.write(f"CREATE OR REPLACE PROCEDURE ST_{dsnmBd}.SP_MRG_{sptbnm} (IN p_base_date DATE, IN p_instance STRING)\n")
f.write("BEGIN\n\n")

#  (24/04/04, 이은송c) GMESHQP인 경우 다이나믹 쿼리를 사용하지 않으므로, TGT_TABLE_NAME을 사용 (SP명은 GV까지만)
if postfix == 'GMESHQP':
    sptbnm = tgtTbnm

# partition table & partition column no modify
if part_yn == 'Y' and part_mod_yn == 'N':
    f.write(f"""\tDECLARE min_ptt DATE;

\tSET min_ptt = (
""")

    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2', 'TIMESTAMP WITHOUT TIME ZONE'):
        f.write(f"\t\tSELECT DATE(MIN({ptt_col_nm}))\n")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\t\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(CAST(MIN({ptt_col_nm}) AS STRING),1,8))\n')
    else:
        f.write(f'\t\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(MIN({ptt_col_nm}),1,8))\n')

    f.write(f"""\t\tFROM ST_{dsnmBd}.{sptbnm}
\t\tWHERE p_ptt >= p_base_date\n""")

    if mult_inst_flag == "Y":
        f.write(f"\t\tAND INSTANCE = p_instance\n")

    f.write(f"""\t);

""")

# L0 Target Merge Statement

f.write(f"""\t-- L0 Target merge statement
\tMERGE INTO L0_{dsnmBd}.{sptbnm} T
\tUSING(
\t\tSELECT
""")

# source columns(using에서 사용)
for r, row in enumerate(rsltAllCols):
    if r > 0:
        f.write("\t\t\t,")
    else:
        f.write("\t\t\t")

    v_comment = row['comments'].replace('\n', '').replace('\r', '')

    if v_comment != "":
        # f.write(f"{row[3]}\t\t-- {v_comment}\n") -- 커맨트 부여시 infa에서 실행할때 charset 에러가 나므로 일단 보류
        f.write(f"{row['column_name']}\n")
    else:
        f.write(f"{row['column_name']}\n")

f.write(f"""\t\tFROM ST_{dsnmBd}.{sptbnm}
\t\tWHERE p_ptt >= p_base_date""")

if part_yn == 'Y':
    if mult_inst_flag == "Y":
        f.write(f"\n\t\tAND INSTANCE = p_instance")

f.write("\n\t\t) S\n")

for r, row in enumerate(rsltKeyCols):
    if r > 0:
        f.write("\tAND ")
    else:
        f.write("\tON ")

    f.write(f"T.{row['column_name']} = S.{row['column_name']}\n")

# p_ptt가 NUll일 경우 p_base_dsate와의 비교조건에서 빠지게 되어 Null 데이터가 중복 Insert 되는 문제점 있음.
# p_ptt도 IFNULL로 감싸도록 변경 (김현진C, 09/05)
# p_ptt를 IFNULL로 감쌀 경우 파티션 pruning을 하지 않으므로 or IS NULL로 변경함 (김현진C, 09/21)

if part_yn == 'Y' and part_mod_yn == 'N':
    f.write("\tAND (T.p_ptt >= min_ptt or T.p_ptt IS NULL)\n")

f.write("\tWHEN MATCHED THEN\n")
f.write("\tUPDATE SET\n")

if part_yn == 'Y' and part_mod_yn == 'Y':
    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2', 'TIMESTAMP WITHOUT TIME ZONE'): # DATETIME2 추가(20211118,한병학)
        f.write(f"\t\tT.p_ptt = DATE(S.{ptt_col_nm})\n\t\t,")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\t\tT.p_ptt = PARSE_DATE("%Y%m%d", SUBSTR(CAST(S.{ptt_col_nm} AS STRING),1,8))\n\t\t,')
    else:
        f.write(f'\t\tT.p_ptt = PARSE_DATE("%Y%m%d", SUBSTR(S.{ptt_col_nm},1,8))\n\t\t,')
else:
    f.write("\t\t")

f.write("T.etl_load_ts = CURRENT_TIMESTAMP()\n")

for r, row in enumerate(rsltNonKeyCols):
    f.write(f"\t\t,T.{row['column_name']} = S.{row['column_name']}\n")

f.write(f"""\tWHEN NOT MATCHED THEN
\tINSERT (
""")

if part_yn == 'Y':
    f.write("\t\tp_ptt\n\t\t,")
else:
    f.write("\t\t")
# f.write("\t\tp_ptt\n\t\t,")

f.write("etl_load_ts\n")

for r, row in enumerate(rsltAllCols):
    f.write(f"\t\t,{row['column_name']}\n")

f.write("\t)\n\tVALUES (\n")

if part_yn == 'Y':
    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2', 'TIMESTAMP WITHOUT TIME ZONE'):
        f.write(f"\t\tDATE(S.{ptt_col_nm})\n\t\t,")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\t\tPARSE_DATE("%Y%m%d", SUBSTR(CAST(S.{ptt_col_nm} AS STRING),1,8))\n\t\t,')
    else:
        f.write(f'\t\tPARSE_DATE("%Y%m%d", SUBSTR(S.{ptt_col_nm},1,8))\n\t\t,')
else:
    f.write("\t\t")
# f.write("\t\t'9999-12-31'\n\t\t,")

f.write("CURRENT_TIMESTAMP()\n")

for r, row in enumerate(rsltAllCols):
    f.write(f"\t\t,S.{row['column_name']}\n")

f.write("\t);\n\nEND;\n\n")

f.close()
# 작업완료 표시 - (이은송C, 2023.12.15)
print(f"{foldernm}/{addDir} 폴더 하위 {filenm}가 생성되었습니다.")
