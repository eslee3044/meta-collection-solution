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

args = vars(ap.parse_args())

table_name = args["table"]
system = args["system"]
postfix = args["postfix"]
instance_nm = args["instance"]
owner_nm = args["owner"]

conn = psycopg2.connect(host='', user='', password='', dbname='')
curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

sqlSelTab = f"""
SELECT system_cd
	, postfix
	, owner
	, table_name
	, database_name
	, tgt_ds_cd
	, tgt_table_name
	, tgt_database_name
	, partition_col_modifiable_yn
FROM eapet.tb_meta_tables_ext
WHERE system_cd = '{system}'
AND table_name = '{table_name}'
AND postfix = '{postfix}'
"""

curs.execute(sqlSelTab)
rsltTab = curs.fetchall()
for rowTab in rsltTab:
    srcTbnm = rowTab['table_name']
    tgtTbnm = rowTab['tgt_table_name']
    system = rowTab['system_cd']
    postfix = rowTab['postfix']
    owner = rowTab['owner']
    db_type = rowTab['database_name'].lower()

    break;  # 한 row만 필요함

dsnmBd = system

if db_type in ("mysql", "mariadb"):
    db_type = "mysql"
elif db_type == "db2 udb":
    db_type =  "db2"
elif db_type in ("ms sql server", "ms-sql server","microsoft sql server"):
    db_type = "mssql"
elif db_type == "postgresql":
    db_type = "postgres"
else:
    db_type


# 폴더 경로가 존재하지 않으면 생성
foldernm = 'init_dag'
filenm = f'{db_type.lower()}_init_{system.lower()}_{table_name}_dag.py'

# 파일 열기
with open(f'{foldernm}/{filenm}', 'w', encoding='utf-8') as f:
    f.write(f"""
from airflow import DAG 
from airflow.operators.python import PythonOperator 
from airflow.utils.task_group import TaskGroup 
from common.InitLoadOperator import extract_source, get_source_query, load_to_bigquery 
from datetime import datetime, timedelta 
import pendulum 

default_args = {{
    'owner': 'airflow',
    'retries': 0
}}     
table_name = '{table_name}'
que = 'queue5'
""")

    if postfix == "N":
        src_conn_id = f"{db_type.lower()}_{system.lower()}_prd"
        f.write(f"""
params = {{
    'src_conn_id': '{src_conn_id}',
    'sys_code': '{dsnmBd}',
    'schema_name': '{owner}',
    'table_name': table_name, 
    'partition_yn': 'Y',
    # 'sql_query' : 
}}     
""")
    else:
        src_conn_id = f"{db_type.lower()}_{system.lower()}_{postfix.lower()}_prd"

        f.write(f"""
params = {{
    'src_conn_id': '{src_conn_id}',
    'sys_code': '{dsnmBd}',
    'schema_name': '{owner}',
    'table_name': table_name, 
    'target_table_name': '{table_name}_{postfix}',
    'partition_yn': 'Y',
    # 'sql_query' : 
}}     
""")
    
    f.write(f"""
# DAG 정의
with DAG(
     f'{db_type.lower()}_{system.lower()}_init_{{table_name}}',
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
    tags=['{system.lower()}','{db_type.lower()}','init','hn3']
) as dag:
    def call_function(func, **context):
        params = context['params']
        return func(params)

    def compare_results(**context):
        ti = context['ti']
        extract_task_result = ti.xcom_pull(task_ids='etl_functions.extract_task')
        load_task_result = ti.xcom_pull(task_ids='etl_functions.load_task')
        is_equal = extract_task_result == load_task_result
        return is_equal
        
    with TaskGroup(group_id='etl_functions') as tg:
        extract_task = PythonOperator(
            task_id='extract_task',
            python_callable=call_function,
            op_kwargs={{'func': extract_source, 'params': params}},
            provide_context=True
        )

        load_task = PythonOperator(
            task_id='load_task',
            python_callable=call_function,
            op_kwargs={{'func': load_to_bigquery, 'params': params}},
            provide_context=True
        )

        extract_task >> load_task

    compare_task = PythonOperator(
        task_id='compare_results',
        python_callable=compare_results,
        provide_context=True,
        queue=que
    )
    tg >> compare_task
""")
