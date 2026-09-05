import os
import psycopg2
from psycopg2.extras import DictCursor
import argparse

# 엑셀 연동하여 값 전달
ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-p", "--postfix", required=True, help="테이블 접미사")
ap.add_argument("-i", "--instance", required=True, help="INSTANCE_NAME (ex) APNGSFSP, LGNBHP ...")
ap.add_argument("-o", "--owner", required=True, help="Owner (ex) LGHIRUNP, XXPPS")
ap.add_argument("-d", "--update_col", required=False, help="Update base (ex) , LAST_UPDATE_DATE")

args = vars(ap.parse_args())

table_name = args["table"]
system = args["system"]
postfix = args["postfix"]
instance_nm = args["instance"]
owner_nm = args["owner"]
update_col = args["update_col"]

# Postgres Connection 연결
conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

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
WHERE system_cd = '{system}'
AND table_name = '{table_name}'
AND postfix = '{postfix}'
"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()
for rowTab in rsltTab:
    instDivCd = rowTab['instance_div_cd']
    srcTbnm = rowTab['table_name']
    tgtTbnm = rowTab['tgt_table_name']
    system = rowTab['system_cd']
    postfix = rowTab['postfix']

    break;  # 한 row만 필요함

dsnmBd = system
 
sqlSelCol = f"""
 SELECT C.system_cd
    , T.tgt_table_name
    , T.database_name  
    , C.owner
    , C.table_name
    , C.column_name
    , T.instance_name 
    , MAX(C.column_id) column_id
    , MAX(C.data_type) data_type
    , coalesce(MAX(C.data_length),0) data_length
    , coalesce(MAX(C.data_precision),0) data_precision
    , coalesce(MAX(C.data_scale),0) data_scale
    , MAX(C.null_yn) null_yn
    , MAX(C.pk_yn) pk_yn
    , MAX(C.partition_key_yn) partition_key_yn
    , MAX(C.cluster_key_yn) cluster_key_yn
    , MAX(C.update_base_yn) update_base_yn
 FROM eapet.tb_meta_columns_ext C
 JOIN eapet.tb_meta_tables_ext T
    ON T.system_cd = C.system_cd
   AND T.instance_name = C.instance_name
   AND T.owner = C.owner
   AND T.table_name = C.table_name
 WHERE 1=1 
    AND C.system_cd = '{system}'
    AND C.table_name = '{table_name}' 
    AND C.postfix = '{postfix}' """
# if system not in ['GMES', 'NBES', 'GSFS', 'GFMS', "GME2"]:  # 매핑 공유 시스템들이 아닌 경우
#     sqlSelCol += f"""AND C.POSTFIX = '{postfix}'"""

sqlSelCol += f"""GROUP BY C.system_cd, T.database_name, C.owner, C.table_name, C.column_name, T.instance_name, T.tgt_table_name 
ORDER BY tgt_table_name, column_id
"""


def py_write(file_obj, db_type):
  if db_type == "oracle" :
    operator = "OracleToBigQueryOperator"
  elif db_type == "vertica":
    operator = "VerticaToBigQueryOperator" 
  elif db_type in ("mysql", "mariadb"):
    operator = "MysqlToBigQueryOperator"
    db_type = "mysql"
  elif db_type == "db2 udb":
    operator = "DB2ToBigQueryOperator"
    db_type =  "db2"
  elif db_type in ("ms sql server", "ms-sql server","microsoft sql server"):
    operator = "MSSQLToBigQueryOperator"
  elif db_type == "postgresql":
    operator = "PostgresToBigQueryOperator"
    db_type = "postgres"

  if system == 'GME2' or system == 'GMES':
    postfix = instance_nm
    tag_list = [f'"{system.lower()}"', f'"{db_type.lower()}"', f'"{postfix.lower()}"']
  else:
    postfix = "N"
    tag_list = [f'"{system.lower()}"', f'"{db_type.lower()}"']

  # tag_list를 문자열로 변환
  tags_str = ', '.join(tag_list)

  dag_py = f"""
from airflow import DAG
from common.{operator} import {operator}
from common.commonUtil import *
from datetime import timedelta, datetime
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup
import pendulum  \n

default_args = {{
    'owner': 'airflow',
    'retries': 0,
}}     \n

dag_keys = {{
    'env': 'prd',     # dev or prd 
    'system_name': 'eap',
    'data_layer': 'lnd0',
    'src_system': '{system.lower()}',
    'table_name': '{table_name.lower()}',
    'src_db_type': '{db_type}',
    'src_region' : '{postfix.lower()}'
}}     \n

dag_id, sql_file_path, src_conn_id, tgt_conn_id, tgt_dataset_id, tgt_table_name, tgt_procedure_name = get_bqDag_attr2(dag_keys)    \n

dag = DAG(
    dag_id=dag_id,
    default_args=default_args,
    schedule_interval=None,
    start_date=datetime(2024, 7, 1, 0, 0, 0, tzinfo=pendulum.timezone('Asia/Seoul')),  # 특정 날짜 및 시간 설정
    catchup=False,
    tags = [{tags_str}]
)     \n

with TaskGroup("db_bq_group", dag=dag) as db_bq_group:


    db_to_bq = {operator}(
        task_id='db_to_lnd0_task',
        src_sql_filepath= sql_file_path ,  #소스 sql 파일 경로
        src_conn_id=src_conn_id,  #소스 airflow 커넥션명
        tgt_conn_id=tgt_conn_id,  #타겟 airflow 커넥션명
        tgt_dataset_id=tgt_dataset_id,  #타겟 dataset ID
        tgt_table_name=tgt_table_name,  #타겟 테이블명
        tgt_procedure_name=tgt_procedure_name,  # BigQuery 프로시저 이름
        tgt_procedure_params={{'Day': 0, 'Instance_Name': '{postfix.upper()}'}},  # BigQuery 프로시저 파라미터
        dag=dag
    )

    def call_gen_meta_log(**context):
        text = context['ti'].xcom_pull(key='return_value')
        dag_id = text['dag_id']
        total_rows = text['total_rows']
        batch_type = text['batch_type']
        run_id = text['run_id']
        trigger_mn_log(dag_id, total_rows, batch_type, run_id)

    call_gen_meta_log = PythonOperator(
        task_id = 'call_gen_meta_log',
        python_callable=call_gen_meta_log,
        trigger_rule="all_done",
        dag=dag
    )

    db_to_bq >> call_gen_meta_log

def check_previous_task_status(**context):
    text = context['ti'].xcom_pull(key='return_value')
    dag_id = text['dag_id']
    run_id = text['run_id']

    _, task_df, _ = extract_meta_info(dag_id, run_id)
    task_state = task_df['state'][0].lower()

    # 상태를 체크
    if task_state == 'failed':
        raise Exception("Previous task failed.")
    else:
        pass

check_task = PythonOperator(
    task_id='check_task',
    python_callable=check_previous_task_status,
    # trigger_rule="all_done",
    dag=dag
)


db_bq_group >> check_task
"""
  with open(file_obj, 'w', encoding = 'utf-8') as file_obj:
    file_obj.write(dag_py.strip() + "\n")

def sql_write(file_obj, query_col):
    curs.execute(query_col)
    rsltCol = curs.fetchall()
    columns = []  # 'column' 대신 'columns'로 변경 (복수형)
    for row in rsltCol:
        column_name = row['column_name']
        column_type = row['data_type'].lower()
        db_type = row['database_name'].lower()

        # PostgreSQL 전용 처리
        if db_type == 'postgresql':
            if column_type in ('double', 'double precision'):
                columns.append(f"ROUND(CAST({column_name} AS numeric), 9) AS {column_name}")
            elif column_type in ('number', 'float', 'decimal', 'numeric'):
                columns.append(f"ROUND({column_name}, 9) AS {column_name}")
            elif column_type in ('date'):
                columns.append(f"TO_CHAR({column_name}, 'YYYY-MM-DD') AS {column_name}")
            else:
                columns.append(f"{column_name}")
        # PostgreSQL 외 처리
        else:
            if column_type in ('number', 'float', 'double', 'decimal', 'numeric', 'double precision'):
                columns.append(f"ROUND({column_name}, 9) AS {column_name}")
            else:
                columns.append(f"{column_name}")

    # 'columns' 리스트를 제대로 사용하여 쿼리 문자열을 생성
    query = f"SELECT\n    " + ",\n    ".join(columns) + "\n"

    if instDivCd is None:
        query += f'FROM {owner_nm}.{table_name}'
    else:
        query += f"""    '{instDivCd}' AS INSTANCE \n FROM {owner_nm}.{table_name}"""   #GSFS용
      
    with open(file_obj, "w", encoding='utf-8') as file:
        file.write(query)


## db2는 버전이슈 > 수동으로 조건 지정

def sql_write_condition(file_obj,db_type):
  if db_type == "oracle" :
    condition = f'''WHERE 1=1 AND {update_col} >= TO_DATE('{{start_time}}', '{{date_format}}') AND {update_col} <= TO_DATE('{{end_time}}', '{{date_format}}')'''
  elif db_type == "vertica":
    condition = f''' WHERE 1=1 AND {update_col} >= TO_TIMESTAMP('{{start_time}}', '{{date_format}}') AND {update_col} <= TO_TIMESTAMP('{{end_time}}', '{{date_format}}')'''
  elif db_type in ("mysql", "mariadb"):
    condition = f''' WHERE 1=1 AND ({update_col} >= STR_TO_DATE('{{start_time}}', '{{date_format}}') AND {update_col} <= STR_TO_DATE('{{end_time}}', '{{date_format}}'))'''
  #elif db_type.startswith("db2"):
  #  condition = f''' WHERE 1=1 AND (  {update_col} >= TO_DATE('{{start_time}}', '{{date_format}}') AND {update_col} < TO_DATE('{{end_time}}', '{{date_format}}')) '''
  elif db_type in ("ms sql server", "ms-sql server","microsoft sql server"):
#    condition = f''' WHERE 1=1 AND ({update_col} >= FORMAT('{{start_time}}','{{date_format}}') AND {update_col} < FORMAT('{{end_time}}','{{date_format}}') ) '''
    condition = f'''WHERE 1=1 AND ({update_col} >= FORMAT(CAST('{{start_time}}' AS DATETIME), '{{date_format}}') AND {update_col} <= FORMAT(CAST('{{end_time}}' AS DATETIME), '{{date_format}}')) '''


  elif db_type == "postgresql":
    condition = f''' WHERE 1=1 AND ({update_col} >= TO_DATE('{{start_time}}', '{{date_format}}') AND {update_col} < TO_DATE('{{end_time}}', '{{date_format}}') + 1)'''
  else :
    condition = f''' WHERE 1=1 AND {update_col} '''

  with open(file_obj, "a", encoding= 'utf-8') as file_obj:
    file_obj.write("\n"+ condition)


def main():
  conn = psycopg2.connect(host=os.environ['ETL_DB_HOST'], user=os.environ['ETL_DB_USER'], password=os.environ['ETL_DB_PASSWORD'], dbname=os.environ['ETL_DB_NAME'])
  curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

  curs.execute(sqlSelTab)
  rsltTab = curs.fetchall()
  for row in rsltTab:
    db_type = row["database_name"].lower()  
    system = row['system_cd']

  if postfix == "N" and system not in ('GSFS', 'NBES', "GMES", "GME2"):
    file_name_py = f"dag/lnd0_{system.lower()}__{table_name.lower()}_dag.py"
    file_name_sql = f"sql/lnd0_{system.lower()}__{table_name.lower()}.sql"
  elif system == 'GME2' or system == "GMES"  :
    file_name_py = f"dag/lnd0_{system.lower()}_{instance_nm.lower()}_{table_name.lower()}_dag.py"
    file_name_sql = f"sql/lnd0_{system.lower()}_{instance_nm.lower()}_{table_name.lower()}.sql"
  elif system == 'GSFS' and instDivCd is not None :
    file_name_py = f"dag/lnd0_{system.lower()}__{table_name.lower()}_dag.py"
    file_name_sql = f"sql/lnd0_{system.lower()}_{instDivCd.lower()}_{table_name.lower()}.sql"
  else :
    file_name_py = f"dag/lnd0_{system.lower()}__{table_name.lower()}_dag.py"
    file_name_sql = f"sql/lnd0_{system.lower()}__{table_name.lower()}.sql"

  py_write(file_name_py,db_type)
  sql_write(file_name_sql, sqlSelCol)
  # if update_col is not None :
  #   sql_write_condition(file_name_sql,db_type)

if __name__ == "__main__":
    main()


