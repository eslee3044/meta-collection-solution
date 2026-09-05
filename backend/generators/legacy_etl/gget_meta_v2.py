import argparse
import psycopg2
import os
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("-s", "--system"   , required=True,  help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-i", "--DBInstance"   , required=True,  help="DB Instance name (ex) GMESCRP or GQMSPROD or OBS2 ")
ap.add_argument("-o", "--owner"        , required=True,  help="SYSTEM CODE (ex) EZMES or RMS_MGR ...")
ap.add_argument("-t", "--table"        , required=True,  help="Table name (ex) IFS_VD_LINE_CAPACITY, ...")
ap.add_argument("-p", "--postfix"      , required=True,  help="Postfix for table name (ex) GP or US or OS or GMESCRP")
ap.add_argument("-f", "--excelfile"    , required=True,  help="Excel File Path (ex) ./output/AllTabCols_20200825.xlsx")

ap.add_argument("-d", "--tgtDbType" , required=False,help="INFA Session Rule (ex) BigQuery")
ap.add_argument("-k", "--instColDiv", required=False,help="INFA Session Rule (ex) ... ")
ap.add_argument("-e", "--sessRule"  , required=False,help="INFA Session Rule (ex) s_m_%SYSTEM_CD%_%INSTANCE_NAME%_%TABLE_NAME%")
ap.add_argument("-m", "--mappRule"  , required=False,help="INFA Mapping Rule (ex) m_%SYSTEM_CD%_%TABLE_NAME%")
ap.add_argument("-b", "--tgtRule"   , required=False,help="INFA Target Table Rule (ex) %SYSTEM_CD%_%TABLE_NAME%")
ap.add_argument("-c", "--partColMod", required=False,help="Partition Column Modification YN (ex) Y or N")

args = vars(ap.parse_args())

sysCd	      = args["system"]
dbinstance	  = args["DBInstance"]
owner         = args["owner"]
tbnm	      = args["table"]
postfix	      = args["postfix"]
xlsnm	      = args["excelfile"]

tgtDbType   = args["tgtDbType"]
instColDiv  = args["instColDiv"]
sessRule    = args["sessRule"]
mappRule    = args["mappRule"]
tgtRule     = args["tgtRule"]
partColMod  = args["partColMod"]
usernm      = os.getenv('USERNAME')

# 메타샵 DB 연결
conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor()

# Table List Split
tbnmlist = f"{tbnm}""".split(',')
tbnmlist2 = ','.join("'"+str(e)+"'" for e in tbnmlist)

#####################################################
#				Get Columns Info
#####################################################
# inf_md_col Full scan을 피하기 위해 쿼리 튜닝함(join을 피하기 위해 inf_md_col이 메인 테이블에 위치하며, 테이블 개수만큼 반복수행함)
df_col = pd.DataFrame()
for tb in tbnmlist:
    sqlSelAllTabCols = f"""
    SELECT 
          '{sysCd}'           AS SYSTEM_CD 
        , '{dbinstance}'      AS INSTANCE_NAME
        , '{postfix}' 	      AS POSTFIX
        , UPPER('{owner}')	  AS OWNER
        , UPPER('{tb}')      AS TABLE_NAME
        , UPPER(C.COL_NM)     AS COLUMN_NAME
        , C.COL_PSTN          AS COLUMN_ID
        , UPPER(C.DATA_TYPE_NM)      AS DATA_TYPE
        , C.DATA_TYPE_LEN     AS DATA_LENGTH
        , C.DATA_TYPE_PREC    AS DATA_PRECISION 
        , C.DATA_TYPE_SCAL    AS DATA_SCALE
        , C.NULL_YN           AS NULL_YN 
        , CASE 
            WHEN C.PK_YN IS NULL THEN 'N'
            ELSE C.PK_YN  
          END                 AS PK_YN
        , 'N'                 AS PARTITION_KEY_YN
        , 'N'                 AS CLUSTER_KEY_YN
        , 'N'                 AS UPDATE_BASE_YN
        , 'N'                 AS TO_SINGLE_BYTE_YN
        , 'N'                 AS SUBSTR_YN
        , C.COL_CMNT          AS COMMENTS
        , TO_CHAR(CURRENT_TIMESTAMP,'YYYY-MM-DD HH24:MI:SS')   AS CREATEDON
        , '{usernm}'          AS CREATEDBY          
        , TO_CHAR(CURRENT_TIMESTAMP,'YYYY-MM-DD HH24:MI:SS')   AS LASTUPDATED
        , '{usernm}'          AS UPDATEDBY
    from (select * 
        from (select
                *, ROW_NUMBER() OVER(PARTITION BY OBJ_ID, COL_ID ORDER BY AVAL_ST_DT DESC) AS RN3
            FROM INF_MD_COL
            where OBJ_ID in (select OBJ_ID
                            from (SELECT 
                                    *, ROW_NUMBER() OVER(PARTITION BY OBJ_ID ORDER BY AVAL_ST_DT DESC) AS RN2 
                                FROM INF_MD_OBJ
                                where 1=1
                                and UPPER(OBJ_NM) = UPPER('{tb}')
                                and UPPER(ACCT_ID) = UPPER('{owner}')
                                and INST_ID = (select distinct INST_ID from INF_MD_INST where INST_NM = '{dbinstance}')
                                ) T
                            where T.RN2 = 1
                            and T.REG_TYP_CD <>'D'
                          ) 
            ) T
        where T.RN3 = 1 
        and T.REG_TYP_CD <> 'D') C
    ORDER BY TABLE_NAME, COLUMN_ID;
    """

    df_col_tmp = pd.read_sql(sqlSelAllTabCols, conn)
    if len(df_col_tmp) == 0:
        print('{}: 테이블 조회결과 없음. 테이블명 재확인하세요.)'.format(tb))
    else:
        print('{}: 테이블 조회 성공)'.format(tb))
    df_col_tmp.columns = map(lambda x: str(x).upper(), df_col_tmp.columns)
    df_col = pd.concat([df_col, df_col_tmp])

#####################################################
#				Get Tables Info
#####################################################

etlConn = '{etlsrcConn}'

if not tgtDbType:
    tgtDbType = 'BigQuery'
if not instColDiv:
    instColDiv = ''
if not sessRule:
    if sysCd in ['GMES','GSFS','NBES','GFMS']:
        sessRule = 's_m_%SYSTEM_CD%_%INSTANCE_NAME%_%TABLE_NAME%'
    else:
        sessRule = 's_m_%SYSTEM_CD%_%TGT_TABLE_NAME%'


if not mappRule:
    if sysCd in ['GMES','GSFS','NBES','GFMS']:				# 매핑 공유 시스템들
        mappRule = 'm_%SYSTEM_CD%_%TABLE_NAME%'
    else:
        mappRule = 'm_%SYSTEM_CD%_%TGT_TABLE_NAME%'
if not tgtRule:
    if sysCd in ['GMES', 'GSFS', 'NBES', 'GFMS']:  			# 매핑 공유 시스템들
        tgtRule = '%SYSTEM_CD%_%TABLE_NAME%'
    else:
        tgtRule = '%SYSTEM_CD%_%TGT_TABLE_NAME%'
if not partColMod:
    partColMod = 'N'


sqlSelAllTables = f"""
SELECT 
     '{sysCd}'                                  AS SYSTEM_CD
    ,'{dbinstance}'      						AS INSTANCE_NAME
    ,'{postfix}'                                AS POSTFIX
    ,UPPER(O.ACCT_ID)                           AS OWNER 
    ,UPPER(O.OBJ_NM)                            AS TABLE_NAME
    ,C.CD_NM                                    AS DATABASE_NAME
    ,CASE
        WHEN C.CD_NM = 'ORACLE'         THEN 'Oracle'
        WHEN C.CD_NM = 'MS SQL SERVER'  THEN 'ODBC'
        WHEN C.CD_NM = 'MYSQL'          THEN 'ODBC'
        WHEN C.CD_NM = 'MARIADB'        THEN 'ODBC'
        WHEN C.CD_NM = 'POSTGRESQL'     THEN 'ODBC'
     END                                        AS ETL_CONN_DIV_CD
    ,'{etlConn}'                                AS ETL_CONN_NM
    ,CONCAT('ST_','{sysCd}')                    AS TGT_DS_CD 
    , CASE
        WHEN '{postfix}' = 'N' THEN UPPER(O.OBJ_NM)     
        WHEN '{postfix}' <> 'N' THEN CONCAT(UPPER(O.OBJ_NM),'_','{postfix}')
      END                                       AS TGT_TABLE_NAME
    ,'{tgtDbType}'                              AS TGT_DATABASE_NAME
    ,CASE 
        WHEN '{dbinstance}' = 'APNGSFSP' THEN 'Asia'
        WHEN '{dbinstance}' = 'EMNGSFSP' THEN 'Europe'
        WHEN '{dbinstance}' = 'AMNGSFSP' THEN 'America'
        WHEN '{dbinstance}' = 'RUNGSFSP' THEN 'Russia'
        WHEN '{dbinstance}' = 'LGNBHP' THEN 'LGNBHP'
        WHEN '{dbinstance}' = 'LGNBEP' THEN 'LGNBEP'
        ELSE NULL
    END                                                     AS INSTANCE_DIV_CD
    ,O.OBJ_CMNT                                             AS COMMENTS 
    , TO_CHAR(CURRENT_TIMESTAMP,'YYYY-MM-DD HH24:MI:SS')    AS CREATEDON
    , '{usernm}'                                            AS CREATEDBY          
    , TO_CHAR(CURRENT_TIMESTAMP,'YYYY-MM-DD HH24:MI:SS')    AS LASTUPDATED
    , '{usernm}'                                            AS UPDATEDBY
    , '{sessRule}'                                          AS SESS_NAME_RULE
    , '{mappRule}'                                          AS MAPP_NAME_RULE
    , '{tgtRule}'                                           AS TGT_NAME_RULE
    , '{partColMod}'                                        AS PARTITION_COL_MODIFIABLE_YN
FROM INF_MD_INST I 
LEFT JOIN (SELECT 
                CD_ID, CD_NM
            FROM MS_CODE 
            WHERE UP_CD_ID = '0001'
                  and LANG_CD = 'ko'
    ) C    -- DBMS 유형 코드 룩업 테이블
    ON I.DB_TYPE = C.CD_ID
LEFT JOIN (SELECT 
                *, ROW_NUMBER() OVER(PARTITION BY INST_ID, ACCT_ID, OBJ_ID ORDER BY AVAL_ST_DT DESC) AS RN1 
            FROM INF_MD_OBJ
    ) O
    ON UPPER(I.INST_ID) = UPPER(O.INST_ID )
WHERE 1=1
AND O.RN1 = 1
AND O.REG_TYP_CD <>'D'
AND UPPER(I.INST_NM) = UPPER('{dbinstance}')
AND UPPER(O.ACCT_ID) = UPPER('{owner}')
AND UPPER(O.OBJ_NM) IN ({tbnmlist2})
"""


# Output File
excelfile  = xlsnm
sheetname  = 'Columns'
sheetname2 = 'Tables'


df_table = pd.read_sql(sqlSelAllTables, conn)
df_table.columns = map(lambda x: str(x).upper(), df_table.columns)

if not os.path.exists(excelfile):
    with pd.ExcelWriter(excelfile, mode='w', engine='openpyxl') as writer:
        df_col.to_excel(writer, sheet_name=sheetname, index=False)
else:
    with pd.ExcelWriter(excelfile, mode='a', engine='openpyxl') as writer:
        df_col.to_excel(writer, sheet_name=sheetname, index=False)

if not os.path.exists(excelfile):
    with pd.ExcelWriter(excelfile, mode='w', engine='openpyxl') as writer:
        df_table.to_excel(writer, sheet_name=sheetname2, index=False)
else:
    with pd.ExcelWriter(excelfile, mode='a', engine='openpyxl') as writer:
        df_table.to_excel(writer, sheet_name=sheetname2, index=False)
