import argparse
import pymysql
import psycopg2

ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-p", "--postfix", required=False, help="TABLE POSTFIX ex) GP, US, GMESCRP ")
args = vars(ap.parse_args())

tbnm = args["table"]
sysCd = args["system"]
postfix = args["postfix"]

# MySQL Connection 연결
conn = pymysql.connect(host='', user='', password='', dbname='')

# Connection 으로부터 Cursor 생성
curs = conn.cursor(pymysql.cursors.DictCursor)

#####################################################
#				Get Table Info
#####################################################
sqlSelTab = f"""
SELECT SYSTEM_CD
	, POSTFIX
	, OWNER
	, TABLE_NAME
	, DATABASE_NAME
	, ETL_CONN_DIV_CD
	, ETL_CONN_NM
	, TGT_DS_CD
	, TGT_TABLE_NAME
	, TGT_DATABASE_NAME
	, INSTANCE_DIV_CD
	, SESS_NAME_RULE
	, MAPP_NAME_RULE
	, TGT_NAME_RULE
	, PARTITION_COL_MODIFIABLE_YN
FROM edlpp.tb_meta_tables_ext
WHERE SYSTEM_CD = '{sysCd}'
AND TABLE_NAME = '{tbnm}'
AND POSTFIX = '{postfix}'
"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()
for rowTab in rsltTab:
    instDivCd = rowTab['INSTANCE_DIV_CD']
    srcTbnm = rowTab['TABLE_NAME']
    tgtTbnm = rowTab['TGT_TABLE_NAME']
    # dsnm = rowTab['TGT_DS_CD']
    dsnm = rowTab['SYSTEM_CD']
    part_mod_yn = rowTab['PARTITION_COL_MODIFIABLE_YN']

    break;  # 한 row만 필요함

dsnmBd = dsnm # 'ST_' 제외

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
SELECT SYSTEM_CD
	, TABLE_NAME
	, COLUMN_NAME
	, MAX(DATA_TYPE) DATA_TYPE
	, MAX(PK_YN) PK_YN
	, MAX(PARTITION_KEY_YN) PARTITION_KEY_YN
	, IFNULL(MAX(COMMENTS), '') COMMENTS
	, MAX(COLUMN_ID) AS COLUMN_ID
    , MAX(UPDATE_BASE_YN) UPDATE_BASE_YN
FROM edlpp.tb_meta_columns_ext
WHERE SYSTEM_CD = '{sysCd}'
AND TABLE_NAME = '{tbnm}'"""

if sysCd not in ['GMES', 'NBES', 'GSFS', 'GFMS','GME2']:  # 매핑 공유 시스템들이 아닌 경우
    sqlSelCol += f"""AND POSTFIX = '{postfix}'"""

sqlSelCol += f"""GROUP BY SYSTEM_CD, TABLE_NAME, COLUMN_NAME
UNION ALL
-- multi instance의 경우 INSTANCE 컬럼 추가
SELECT '{sysCd}' SYSTEM_CD 
	, '{tbnm}' TABLE_NAME
	, 'INSTANCE' COLUMN_NAME
	, '' DATA_TYPE
	, 'Y' PK_YN
	, 'N' PARTITION_KEY_YN
	, 'INSTANCE 구분 값' COMMENTS
	, 'N' UPDATE_BASE_YN 
	, 99999 AS COLUMN_ID
FROM DUAL
WHERE '{mult_inst_flag}' = 'Y'
ORDER BY COLUMN_ID
"""

curs.execute(sqlSelCol)
rsltAllCols = curs.fetchall()

rsltKeyCols = []
rsltNonKeyCols = []
rsltPttCols = []
rsltUptCols = [] # 24.10.08 이하늘 , UPDEATE_COL 추가

for row in rsltAllCols:
    # print(row)
    if row["PK_YN"] == "Y":  # pk_yn
        rsltKeyCols.append(row)
    else:
        rsltNonKeyCols.append(row)

    if row["PARTITION_KEY_YN"] == "Y":
        rsltPttCols.append(row)

    if row['UPDATE_BASE_YN'] == "Y":             # 24.10.08 이하늘 , UPDEATE_COL 추가
        rsltUptCols.append(row)
# partition information
if len(rsltPttCols) > 0:
    part_yn = "Y"  # 파티션 여부
    ptt_col_nm = rsltPttCols[0]["COLUMN_NAME"]  # 파티션 컬럼명
    ptt_col_data_type = rsltPttCols[0]["DATA_TYPE"]  # 파티션 컬럼 데이터타입
else:
    part_yn = "N"

# 24.10.08 이하늘 , UPDEATE_COL 추가
if len(rsltUptCols) > 0:
    update_yn = "Y"  # 업데이트 컬럼 여부
    update_col_nm = rsltUptCols[0]["COLUMN_NAME"]  # 업데이트 컬럼명
else:
    update_yn = "N"


#  (20/12/15, 김현진c)
sptbnm = ''
if sysCd == 'GMES' and postfix == 'GMESHQP':
    sptbnm = srcTbnm + '_GV'
elif sysCd == 'GMES' or postfix == 'N':
    sptbnm = srcTbnm
elif sysCd == 'GME2' or postfix == 'GMESINCP':
    sptbnm = srcTbnm
else:
    sptbnm = tgtTbnm

# 프로시저 파일 생성 후 print로 생성 파일 정보를 보여주기 위해서 변수로 설정 - (이은송C, 2023.12.15)
foldernm = 'merge'
filenm = f'SP_MRG_{sptbnm}(Merge).sql'

#f = open(f'merge/SP_MRG_{sptbnm}(Merge).sql', 'w', encoding='utf-8')
f = open(f'{foldernm}/{filenm}', 'w', encoding='utf-8')
f.write(f"CREATE OR REPLACE PROCEDURE ST_{dsnmBd}.SP_MRG_{sptbnm} (IN p_base_date DATE, IN p_instance STRING)\n")
f.write("OPTIONS (strict_mode=true)\n")
f.write("BEGIN\n\n")

# partition table & partition column no modify
if part_yn == 'Y' and part_mod_yn == 'N' and sysCd not in  ['GMES', 'NBES', 'GSFS', 'GFMS','GME2','SMIP']:
    f.write(f"""\tDECLARE min_ptt DATE;

\tSET min_ptt = (
""")
    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2'):
        f.write(f"\tSELECT DATE(MIN({ptt_col_nm}))\n")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(CAST(MIN({ptt_col_nm}) AS STRING),1,8))\n')
    else:
        f.write(f'\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(MIN({ptt_col_nm}),1,8))\n')

    f.write(f"""\t\tFROM ST_{dsnmBd}.{sptbnm}
\t\tWHERE p_ptt = p_base_date\n""")

    if mult_inst_flag == "Y":
        f.write(f"\t\tAND INSTANCE = p_instance\n")

    f.write(f"""\t);


""")

elif sysCd == 'SMIP':
    pass
    
else:
    f.write(f'''DECLARE min_ptt DATE;\n\nEXECUTE IMMEDIATE format("""\n''')

    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2'):
        f.write(f"\tSELECT DATE(MIN({ptt_col_nm}))\n")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(CAST(MIN({ptt_col_nm}) AS STRING),1,8))\n')
    else:
        f.write(f'\tSELECT PARSE_DATE("%Y%m%d", SUBSTR(MIN({ptt_col_nm}),1,8))\n')

    f.write(f'''\tFROM ST_{dsnmBd}.{sptbnm}_%s
\tWHERE p_ptt =  @base_date\n\t""", p_instance)
\tINTO MIN_PTT \n 	USING p_base_date AS base_date;
\n''')
    if mult_inst_flag == "Y":
        f.write(f"\t\tAND INSTANCE = p_instance\n")

    # f.write(f"""\nSET MIN_PTT_STRING = CAST(MIN_PTT AS STRING);\n\n""")

# L0 Target Merge Statement
f.write(f"""-- L0 Target merge statement \n""")
if sysCd == 'GME2' or sysCd == 'GMES':
    f.write(f'''EXECUTE IMMEDIATE format("""\n''')
    f.write(f"""\tMERGE INTO L0_{dsnmBd}.{sptbnm}_%s T
    USING(
    \tSELECT 
    """)
else:
    f.write(f"""MERGE INTO L0_{dsnmBd}.{sptbnm} T
    USING(
    \tSELECT 
    """)

# source columns(using에서 사용)
for r, row in enumerate(rsltAllCols):
    if r > 0:
        f.write("\t\t\t,")
    else:
        f.write("\t\t")

    v_comment = row['COMMENTS'].replace('\n', '').replace('\r', '')

    if v_comment != "":
        # f.write(f"{row[3]}\t\t-- {v_comment}\n") -- 커맨트 부여시 infa에서 실행할때 charset 에러가 나므로 일단 보류
        f.write(f"{row['COLUMN_NAME']}\n")
    else:
        f.write(f"{row['COLUMN_NAME']}\n")

row_lst = []
for r, row in enumerate(rsltKeyCols):
    row_lst.append(row['COLUMN_NAME'])

f.write(f"""\t\t\t,row_number() over(partition by {", ".join(row_lst)} order by {update_col_nm} desc) rn \n""")
if sysCd == 'GMES' or sysCd == 'GME2':
    f.write(f"""\t\tFROM ST_{dsnmBd}.{sptbnm}_%s \n """)
    f.write("""\tWHERE p_ptt = @base_date""")
else:
    f.write(f"""\t\tFROM ST_{dsnmBd}.{sptbnm} \n """)
    f.write("""\tWHERE p_ptt = p_base_date""")

if part_yn == 'Y':
    if mult_inst_flag == "Y":
        f.write(f"\n\t\tAND INSTANCE = p_instance")

f.write("\n\t) S\n")

for r, row in enumerate(rsltKeyCols):
    if r > 0:
        f.write("\tAND ")
    else:
        f.write("\tON ")

    f.write(f"T.{row['COLUMN_NAME']} = S.{row['COLUMN_NAME']}\n")

# p_ptt가 NUll일 경우 p_base_dsate와의 비교조건에서 빠지게 되어 Null 데이터가 중복 Insert 되는 문제점 있음.
# p_ptt도 IFNULL로 감싸도록 변경 (김현진C, 09/05)
# p_ptt를 IFNULL로 감쌀 경우 파티션 pruning을 하지 않으므로 or IS NULL로 변경함 (김현진C, 09/21)
# if part_yn == 'Y' and part_mod_yn == 'N' and sysCd != 'SMIP' :
#     f.write("\tAND (T.p_ptt >= min_ptt or T.p_ptt IS NULL)\n")
if sysCd == 'GMES' or sysCd == 'GME2':
    f.write("\tAND (T.p_ptt >= @MIN_PTT or T.p_ptt IS NULL)\n")

f.write("\tAND S.rn = 1 \n")
f.write("\tWHEN MATCHED THEN\n")
f.write("\tUPDATE SET\n")
# f.write(f"\t\tT.p_ptt = DATE(S.{ptt_col_nm}) \n")

if part_yn == 'Y' and part_mod_yn == 'Y':
    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2'): # DATETIME2 추가(20211118,한병학)
        f.write(f"\t\t,T.p_ptt = DATE(S.{ptt_col_nm})\n\t\t,")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\t\t,T.p_ptt = PARSE_DATE("%Y%m%d", SUBSTR(CAST(S.{ptt_col_nm} AS STRING),1,8))\n\t\t,')
    else:
        f.write(f'\t\t,T.p_ptt = PARSE_DATE("%Y%m%d", SUBSTR(S.{ptt_col_nm},1,8))\n\t\t,')
else:
    f.write("\t\t")

f.write("T.etl_load_ts = CURRENT_TIMESTAMP()\n")

for r, row in enumerate(rsltNonKeyCols):
    f.write(f"\t\t,T.{row['COLUMN_NAME']} = S.{row['COLUMN_NAME']}\n")

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
    f.write(f"\t\t,{row['COLUMN_NAME']}\n")

f.write("\t)\n\tVALUES (\n")

if part_yn == 'Y':
    if ptt_col_data_type in ('DATE', 'DATETIME', 'TIMESTAMP', 'TIMESTAMP(6)', 'DATETIME2'):
        f.write(f"\t\tDATE(S.{ptt_col_nm})\n\t\t,")
    elif ptt_col_data_type in ('INT'):
        f.write(f'\t\tPARSE_DATE("%Y%m%d", SUBSTR(CAST(S.{ptt_col_nm} AS STRING),1,8))\n\t\t,')
    else:
        f.write(f'\t\tPARSE_DATE("%Y%m%d",FORMAT_TIMESTAMP("%Y%m%d",S.{ptt_col_nm}))\n\t\t,') # 이하늘 postgre용
        # f.write(f'\t\tPARSE_DATE("%Y%m%d", SUBSTR(S.{ptt_col_nm},1,8))\n\t\t,')
else:
    f.write("\t\t")
# f.write("\t\t'9999-12-31'\n\t\t,")

f.write("CURRENT_TIMESTAMP()\n")

for r, row in enumerate(rsltAllCols):
    f.write(f"\t\t,S.{row['COLUMN_NAME']}\n")

f.write("\t);\n")
if sysCd == 'GMES' or sysCd == 'GME2' :
    f.write('''\t""", p_instance, p_instance) 
    USING p_base_date AS base_date, MIN_PTT as MIN_PTT;\n
''')
# else:        
#     f.write('''\t""", p_instance, p_instance) 
#     USING p_base_date AS base_date; \n
# ''')
f.write("END;\n")

f.close()
# 작업완료 표시 - (이은송C, 2023.12.15)
print(f"{foldernm} 폴더 하위 {filenm}가 생성되었습니다.")



from google.cloud import bigquery
import os

# 서비스 계정 키 파일 경로 설정
key_path = "svcac-edl-prd-etl.json"

client = bigquery.Client.from_service_account_json(key_path)

# 파일에서 쿼리 읽기
try:
    with open(f"{foldernm}/{filenm}", "r") as f:
        content = f.read()

    # 쿼리 실행
    query_job = client.query(content)

    # 쿼리 완료 대기 및 결과 확인
    query_job.result()  # 쿼리 완료까지 대기
    
    print(f"{filenm} 완료")

except Exception as e:
    # 쿼리 에러 발생 시 에러 메시지 출력
    print(f"{filenm} 쿼리 실행 중 오류 발생: {e}")
