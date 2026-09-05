import argparse
import pymysql
import os
import sys
import pandas as pd
import numpy as np
import sqlalchemy as sa

# pip install mysqlclient ; Mysql Client Install
ap = argparse.ArgumentParser()
ap.add_argument("-f", "--excelfile", required=True, help="Excel File Path (ex) ./output/AllTabCols_20200825.xlsx")
ap.add_argument("-s", "--shetname", required=True, help="Excel File Sheet (ex) Columns")
ap.add_argument("-t", "--tablename", required=True, help="Table Name (ex) tb_meta_columns_ext, tb_meta_tables_ext")
ap.add_argument("-q", "--sqlmode", required=False, help="Inspection SQL Mode (ex) Y/N")
args = vars(ap.parse_args())

xlsnm = args["excelfile"]
shtnm = args["shetname"]
tblnm = args["tablename"]
sqlyn = args["sqlmode"]
usernm = os.getenv('USERNAME')

# MySQL Connection 연결
engine = sa.create_engine(os.environ.get("ETL_MYSQL_URL", "mysql+mysqldb://"))
conn = engine.connect()

print(xlsnm)
df = pd.read_excel(xlsnm, sheet_name=shtnm,
                   dtype={'OWNER': str})  # encoding="utf-8" # pandas1.05 works. 1.1.0 not work.!!!

if sqlyn == 'Y':
    #####################################################
    #       Get Table Info From Excel
    #####################################################
    # INSPECT QUERY WOULD TO BE DEFINED


    columns = [ \
        'SYSTEM_CD' \
        , 'INSTANCE_NAME' \
        , 'OWNER' \
        , 'TABLE_NAME' \
        , 'DATABASE_NAME' \
        , 'ETL_CONN_DIV_CD' \
        , 'ETL_CONN_NM' \
        , 'TGT_DS_CD' \
        , 'TGT_TABLE_NAME' \
        , 'TGT_DATABASE_NAME' \
        , 'INSTANCE_DIV_CD' \
        , 'COMMENTS' \
        , 'CREATEDON' \
        , 'CREATEDBY' \
        , 'LASTUPDATED' \
        , 'UPDATEDBY' \
        , 'SESS_NAME_RULE' \
        , 'MAPP_NAME_RULE' \
        , 'TGT_NAME_RULE' \
        , 'PARTITION_COL_MODIFIABLE_YN' \
        , 'TABLE_TYPE' \
        , 'SQL_INSP_YN' \
        , 'SQL_SRC_TCOUNT' \
        , 'SQL_TGT_TCOUNT' \
        , 'SQL_TGT_PK_DUP' \
        ]

    df['TABLE_TYPE'] = '-'
    df['SQL_INSP_YN'] = 'N'
    df['SQL_SRC_TCOUNT'] = None
    df['SQL_TGT_TCOUNT'] = None
    df['SQL_TGT_PK_DUP'] = None

    ## 2020-11-09 추가(KDH)
    df.to_sql(name=tblnm, con=engine, if_exists='append', index=False,
                  dtype={'POSTFIX': sa.VARCHAR(length=100),
                         'OWNER': sa.types.VARCHAR(length=100),
                         'TABLE_NAME': sa.types.VARCHAR(length=256),
                         'DATABASE_NAME': sa.types.VARCHAR(length=50),
                         'ETL_CONN_DIV_CD': sa.types.VARCHAR(length=50),
                         'ETL_CONN_NM': sa.types.VARCHAR(length=50),
                         'TGT_DS_CD': sa.types.VARCHAR(length=100),
                         'TGT_TABLE_NAME': sa.types.VARCHAR(length=300),
                         'TGT_DATABASE_NAME': sa.types.VARCHAR(length=50),
                         'INSTANCE_DIV_CD': sa.types.VARCHAR(length=100),
                         'COMMENTS': sa.types.VARCHAR(length=4000),
                         'CREATEDON': sa.DateTime(),
                         'CREATEDBY': sa.types.VARCHAR(length=50),
                         'LASTUPDATED': sa.DateTime(),
                         'UPDATEDBY': sa.types.VARCHAR(length=50),
                         'SESS_NAME_RULE': sa.types.VARCHAR(length=300),
                         'MAPP_NAME_RULE': sa.types.VARCHAR(length=300),
                         'TGT_NAME_RULE': sa.types.VARCHAR(length=300),
                         'PARTITION_COL_MODIFIABLE_YN': sa.types.VARCHAR(length=1),
                         'TABLE_TYPE': sa.types.VARCHAR(length=1),
                         'SQL_INSP_YN': sa.types.VARCHAR(length=1),
                         'SQL_SRC_TCOUNT': sa.types.NVARCHAR(length=4000),
                         'SQL_TGT_TCOUNT': sa.types.NVARCHAR(length=4000),
                         'SQL_TGT_PK_DUP': sa.types.NVARCHAR(length=4000)})
else:
    df.to_sql(name=f"{tblnm}""", con=engine, if_exists='append', index=False)
                    