#!/usr/local/bin/python3.8
"""
FILENAME        : bq_create_views.sh
DESCRIPTION     : Create authorized views (L0, ST) and save table schema file.
AUTHOR          :
REQUIREMENT     : pandas, google-cloud-bigquery
REVISION HISTORY: 1.0
CMD             : python bq_create_views.py <target dataset> <input file> <output dir>
"""
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
import tempfile
import os
import sys
from os import path
from datetime import datetime
from datetime import date
import pandas as pd
from sqlalchemy import create_engine
# import csv
import argparse
import xml.etree.ElementTree as et

class Logger(object):
    def __init__(self):
        # log_filename = os.path.join('logs', 'create_view.log')
        log_filename = 'create_view.log'  # 로컬PC에서는 같은 폴더에 로그파일 작성.
        print("The current working directory is %s" % log_filename)

        self.terminal = sys.stdout
        self.log = open(log_filename, 'a')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        # this flush method is needed for python 3 compatibility.
        # this handles the flush command by doing nothing.
        # you might want to specify some extra behavior here.
        pass

def make_view_name(bq_src_dataset_name, table_name):
    return "V_" + bq_src_dataset_name[0:2] + bq_src_dataset_name[3:len(bq_src_dataset_name)] + "_" + table_name

def write_log(format_string, *argv):
    format_string = '[{}] ' + format_string
    log_argv = tuple([datetime.today().strftime("%Y-%m-%d %H:%M:%S")]) + argv
    print(format_string.format(*log_argv))

def create_view_catalog(client, project_id, engine, idx, bq_view_query_fmt, bq_view_except_pinfo_query_fmt, bq_create_view_query_fmt):

    my_select_catalog_query_fmt = """
    SELECT 
    tdch.UPDATEDBY as TBL_UPDATEDBY, tdch.ORIGIN_SYSTEM_L, tdch.TABLE_NAME, tdch.DESCRIPTION, tdcl.TABLE_COLUMN, tdcl.COLUMN_ID, tdcl.COLUMN_DATA_TYPE, tdcl.NULL_YN, tdcl.PERSONAL_INFO_YN, tdcl.DESCRIPTION 
    , tdcl.ATTRIBUTE1
    FROM tb_data_catalogue_h tdch, tb_data_catalogue_l tdcl 
    WHERE tdch.CATALOG_CD = tdcl.CATALOG_CD 
    AND upper(tdch.TABLE_NAME) = upper(tdcl.TABLE_NAME) 
    AND substring(tdch.ATTRIBUTE7,4,4)= '{}' AND upper(tdch.TABLE_NAME) = '{}'
    ORDER BY tdch.ORIGIN_SYSTEM_L, tdch.TABLE_NAME, CAST(tdcl.COLUMN_ID AS UNSIGNED )
    """

    bq_select_catalog_query_fmt = """
    SELECT
    C.table_schema, C.table_name, C.column_name, C.ordinal_position, C.data_type, C.is_nullable, CF.description, C.is_partitioning_column, C.clustering_ordinal_position 
    from {}.INFORMATION_SCHEMA.COLUMNS C, {}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS CF
    WHERE C.column_name = CF.column_name AND C.table_name = CF.table_name
    AND C.table_name = '{}'
    order by C.ordinal_position
    """

    result = []
    # bq_src_dataset_name, src_table_name, use_personal_info, where_condition
    view_dataset_id = idx[0].text
    bq_src_dataset_name = idx[1].text
    src_table_name = idx[2].text
    use_personal_info = idx[3].text
    where_condition = idx[4].text
    if where_condition is None: where_condition = ''

    src_system_name = bq_src_dataset_name[3:len(bq_src_dataset_name)]
    bq_st_src_dataset_name = "ST_" + src_system_name
    write_log("[{}] Source info: [{}] {}.{}", idx, src_system_name, bq_src_dataset_name, src_table_name)

    st_view_name = make_view_name(bq_st_src_dataset_name, src_table_name)
    l0_view_name = make_view_name(bq_src_dataset_name, src_table_name)
    l1_view_name = make_view_name(bq_src_dataset_name, src_table_name)

    # get catalog info from mysql
    df_src = pd.read_sql(my_select_catalog_query_fmt.format(src_system_name, src_table_name), con=engine)

    # if table catalog not found in mysql
    if df_src.empty:
        write_log("[{}] SKIP-CATALOG NOT FOUND: {}.{}", view_dataset_id, src_system_name, src_table_name)
        return [view_dataset_id, bq_src_dataset_name, src_table_name, "", "오류 : 카탈로그를 찾을 수 없습니다.", "오류 : 카탈로그를 찾을 수 없습니다.", "", ""]

    if df_src['TBL_UPDATEDBY'].iloc[0] == 'BQ-SYNC':
        write_log("[{}] SKIP-CATALOG UPDATE-BY BQ-SYNC: {}.{}", idx, src_system_name, src_table_name)
        return [view_dataset_id, bq_src_dataset_name, src_table_name, "", "오류 : TBL_UPDATEDBY=BQ-SYNC", "오류 : TBL_UPDATEDBY=BQ-SYNC", "", ""]

    if df_src['ATTRIBUTE1'].iloc[0] == 'CU' and use_personal_info == 'Y':
        write_log("[{}] Unable to create customer table containing personal information column: {}.{}", idx, src_system_name, src_table_name)
        return [view_dataset_id, bq_src_dataset_name, src_table_name, "", "오류 : 카탈로그에 개인정보 확인필요(TB_DATA_CATALOGUE_L.ATTRIBUTE1='CU')", "오류 : 카탈로그에 개인정보 확인필요(TB_DATA_CATALOGUE_L.ATTRIBUTE1='CU')", "", ""]

    # where condition 이 없는 경우 1=1로 셋팅 (김현진C 추가, 20/12/29)
    # 조인을 통해 조건을 가져오는 경우에는 작업 대상 테이블에 alias S를 붙여주고 {}에도 S를 넣어줌
    alias_src_table_name = src_table_name
    if where_condition == '':
        where_condition = '1=1'
    elif '{}' in where_condition:
        alias_src_table_name += ' S'
        where_condition = where_condition.format('S')

    
    select_col_list_portal_personal_n = df_src[df_src['PERSONAL_INFO_YN'] == 'N']['TABLE_COLUMN'].to_list()
    select_col_list_portal_personal_n.append('P_PTT')
    select_col_list_portal_personal_n.append('ETL_LOAD_TS')

    select_col_list_portal_personal_y = df_src['TABLE_COLUMN'].to_list()
    select_col_list_portal_personal_y.append('P_PTT')
    select_col_list_portal_personal_y.append('ETL_LOAD_TS')

    select_col_list_portal_personal_y2 = df_src[df_src['PERSONAL_INFO_YN'] == 'Y']['TABLE_COLUMN'].to_list()
    select_col_list_portal_personal_n = [x for x in select_col_list_portal_personal_n if x not in select_col_list_portal_personal_y2]

    # column check
    if bq_src_dataset_name[0:2] == "L0":
        bq_select_catalog_query_l0 = bq_select_catalog_query_fmt.format(bq_src_dataset_name, bq_src_dataset_name, src_table_name)        # L0
        df_src_bq = client.query(bq_select_catalog_query_l0).to_dataframe()
        select_col_list = []
        select_col_list = df_src_bq['column_name'].to_list()

        select_col_list_n = [x for x in select_col_list if x in select_col_list_portal_personal_n]
        select_col_list_y = [x for x in select_col_list if x in select_col_list_portal_personal_y]

        bq_select_catalog_query_st = bq_select_catalog_query_fmt.format(bq_st_src_dataset_name, bq_st_src_dataset_name, src_table_name)  # ST
        df_src_bq_st = client.query(bq_select_catalog_query_st).to_dataframe()
        select_col_list_st = []
        select_col_list_st = df_src_bq_st['column_name'].to_list()

        select_col_list_st_n = [x for x in select_col_list_st if x in select_col_list_portal_personal_n]
        select_col_list_st_y = [x for x in select_col_list_st if x in select_col_list_portal_personal_y]
    else:
        bq_select_catalog_query_l0 = bq_select_catalog_query_fmt.format(bq_src_dataset_name, bq_src_dataset_name, src_table_name)        # L0
        df_src_bq = client.query(bq_select_catalog_query_l0).to_dataframe()
        select_col_list = []
        select_col_list = df_src_bq['column_name'].to_list()

        select_col_list_n = [x for x in select_col_list if x in select_col_list_portal_personal_n]
        select_col_list_y = [x for x in select_col_list if x in select_col_list_portal_personal_y]

        select_col_list_st_n = []
        select_col_list_st_y = []


    if use_personal_info == 'N':
        select_cols = ','.join(select_col_list_n)
        select_cols_st = ','.join(select_col_list_st_n)
    elif use_personal_info == 'Y':
        select_cols = ','.join(select_col_list_y)
        select_cols_st = ','.join(select_col_list_st_y)


    bq_st_view_query = bq_view_query_fmt.format(select_cols_st, bq_st_src_dataset_name, alias_src_table_name, where_condition.replace("V_L0","V_ST"))
    bq_l0_view_query = bq_view_query_fmt.format(select_cols, bq_src_dataset_name, alias_src_table_name, where_condition)
    bq_l1_view_query = bq_view_query_fmt.format(select_cols, bq_src_dataset_name, alias_src_table_name, where_condition)

    write_log("[{}] Make ST view query: {}", idx, bq_st_view_query)
    write_log("[{}] Make L0 view query: {}", idx, bq_l0_view_query)
    write_log("[{}] Make L1 view query: {}", idx, bq_l1_view_query)

    # create or replace view (ST, L0)
    if bq_src_dataset_name[0:2] == 'L0': 
        bq_create_st_view_query = bq_create_view_query_fmt.format(view_dataset_id, st_view_name, bq_st_view_query)
        try:
            query_job = client.query(bq_create_st_view_query)
            query_job.result()
        except Exception as e: print(e)
        
        bq_create_l0_view_query = bq_create_view_query_fmt.format(view_dataset_id, l0_view_name, bq_l0_view_query)
        try:
            query_job = client.query(bq_create_l0_view_query)
            query_job.result()
        except Exception as e: print(e)
    # create or replace view (L1, A1)
    else:
        bq_create_l1_view_query = bq_create_view_query_fmt.format(view_dataset_id, l1_view_name, bq_l1_view_query)
        try:
            query_job = client.query(bq_create_l1_view_query)
            query_job.result()
        except Exception as e: print(e)

    # grant authorized view (ST, L0)
    if bq_src_dataset_name[0:2] == 'L0': 
        source_dataset_ref = client.get_dataset(bq_st_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        OB_ST_ACL_LIST = [entry.dataset.dataset_id for entry in access_entries if str(entry.dataset) != 'None']
        if view_dataset_id not in OB_ST_ACL_LIST:
            view_reference = {
                "projectId": project_id,
                "datasetId": view_dataset_id,
                "tableId": st_view_name,
            }
            add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
            access_entries.append(add_access_entry)
            source_dataset_ref.access_entries = access_entries
            try:
                source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
                write_log("[{}] Granted ST view access: {}=>{}", idx, bq_st_src_dataset_name, st_view_name)
            except Exception as e: print(e)
        else: write_log("[{}] OB_DATASET-{} Already in {} ACL List", idx, view_dataset_id, bq_st_src_dataset_name)

        source_dataset_ref = client.get_dataset(bq_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        OB_ACL_LIST = [entry.dataset.dataset_id for entry in access_entries if str(entry.dataset) != 'None']
        if view_dataset_id not in OB_ACL_LIST:
            view_reference = {
                "projectId": project_id,
                "datasetId": view_dataset_id,
                "tableId": l0_view_name,
            }
            add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
            access_entries.append(add_access_entry)
            source_dataset_ref.access_entries = access_entries
            try:
                source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
                write_log("[{}] Granted L0 view access: {}=>{}", idx, bq_src_dataset_name, l0_view_name)
            except Exception as e: print(e)
        else: write_log("[{}] OB_DATASET-{} Already in {} ACL List", idx, view_dataset_id, bq_src_dataset_name)

    # grant authorized view (L1)
    else:
        source_dataset_ref = client.get_dataset(bq_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        view_reference = {
            "projectId": project_id,
            "datasetId": view_dataset_id,
            "tableId": l1_view_name,
        }
        add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
        access_entries.append(add_access_entry)
        source_dataset_ref.access_entries = access_entries
        try:
            source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
            write_log("[{}] Granted L1 view access: {}=>{}", idx, bq_src_dataset_name, l1_view_name)
        except Exception as e: print(e)

    write_log("[{}] View job done: {}.{}", idx, bq_src_dataset_name, src_table_name)

    result = [view_dataset_id, bq_src_dataset_name, src_table_name, use_personal_info, l0_view_name, st_view_name, bq_l0_view_query, bq_st_view_query]

    return result

def create_view_no_catalog(client, project_id, idx, bq_view_query_fmt, bq_view_except_pinfo_query_fmt, bq_create_view_query_fmt):

    bq_select_catalog_query_fmt = """
    SELECT
    C.table_schema, C.table_name, C.column_name, C.ordinal_position, C.data_type, C.is_nullable, CF.description, C.is_partitioning_column, C.clustering_ordinal_position 
    from {}.INFORMATION_SCHEMA.COLUMNS C, {}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS CF
    WHERE C.column_name = CF.column_name AND C.table_name = CF.table_name
    AND C.table_name = '{}'
    order by C.ordinal_position
    """

    bq_select_column_query_fmt = """
    SELECT
    C.column_name, C.ordinal_position
    from {}.INFORMATION_SCHEMA.COLUMNS C, {}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS CF
    WHERE C.column_name = CF.column_name AND C.table_name = CF.table_name
    AND C.table_name = '{}'
    order by C.ordinal_position
    """

    result = []
    view_dataset_id = idx[0].text
    bq_src_dataset_name = idx[1].text
    src_table_name = idx[2].text
    use_personal_info = idx[3].text
    where_condition = idx[4].text
    if where_condition is None: where_condition = ''

    src_system_name = bq_src_dataset_name[3:len(bq_src_dataset_name)]
    bq_st_src_dataset_name = "ST_" + src_system_name
    write_log("[{}] Source info: [{}] {}.{}", idx, src_system_name, bq_src_dataset_name, src_table_name)

    st_view_name = make_view_name(bq_st_src_dataset_name, src_table_name)
    l0_view_name = make_view_name(bq_src_dataset_name, src_table_name)
    l1_view_name = make_view_name(bq_src_dataset_name, src_table_name)

    # where condition 이 없는 경우 1=1로 셋팅 (김현진C 추가, 20/12/29)
    # 조인을 통해 조건을 가져오는 경우에는 작업 대상 테이블에 alias S를 붙여주고 {}에도 S를 넣어줌
    alias_src_table_name = src_table_name
    if where_condition == '':
        where_condition = '1=1'
    elif '{}' in where_condition:
        alias_src_table_name += ' S'
        where_condition = where_condition.format('S')

    # personal_col_list = []
    ########### 2020-05-18
    bq_select_catalog_query2 = bq_select_column_query_fmt.format(bq_src_dataset_name, bq_src_dataset_name, src_table_name)
    # bq_select_catalog_query3 = bq_select_column_query_fmt.format(bq_st_src_dataset_name, bq_st_src_dataset_name, src_table_name)  # ST
    df_src_yj = client.query(bq_select_catalog_query2).to_dataframe()
    # df_src_yj2 = client.query(bq_select_catalog_query3).to_dataframe()
    select_col_list = []
    select_col_list = df_src_yj['column_name'].to_list()

    if bq_src_dataset_name[0:2] == "L0":
        bq_select_catalog_query3 = bq_select_column_query_fmt.format(bq_st_src_dataset_name, bq_st_src_dataset_name, src_table_name)  # ST
        df_src_yj2 = client.query(bq_select_catalog_query3).to_dataframe()
        select_col_list_st = []
        select_col_list_st = df_src_yj2['column_name'].to_list()
    else:
        bq_select_catalog_query3 = []
        df_src_yj2 = []
        select_col_list_st = []
        select_col_list_st = []

    if select_col_list != []:

        if use_personal_info == 'N':

            select_cols = ','.join(select_col_list)
            select_cols_st = ','.join(select_col_list_st)
            bq_st_view_query = bq_view_query_fmt.format(select_cols_st, bq_st_src_dataset_name, alias_src_table_name, where_condition.replace("V_L0","V_ST"))
            bq_l0_view_query = bq_view_query_fmt.format(select_cols, bq_src_dataset_name, alias_src_table_name, where_condition)
            bq_l1_view_query = bq_view_query_fmt.format(select_cols, bq_src_dataset_name, alias_src_table_name, where_condition)

        write_log("[{}] Make ST view query: {}", idx, bq_st_view_query)
        write_log("[{}] Make L0 view query: {}", idx, bq_l0_view_query)
        write_log("[{}] Make L1 view query: {}", idx, bq_l1_view_query)
        """
        # create bq view (ST, L0)
        st_view_ref = view_dataset_ref.table(st_view_name)    
        view = bigquery.Table(st_view_ref)
        view.view_query = bq_st_view_query    
        view = client.create_table(view, exists_ok=True)
        write_log("[{}] Created ST view: {}", idx, st_view_name)

        l0_view_ref = view_dataset_ref.table(l0_view_name)    
        view = bigquery.Table(l0_view_ref)
        view.view_query = bq_l0_view_query
        view = client.create_table(view, exists_ok=True)    
        write_log("[{}] Created L0 view: {}", idx, l0_view_name)

        l1_view_ref = view_dataset_ref.table(l1_view_name)    
        view = bigquery.Table(l1_view_ref)
        view.view_query = bq_l1_view_query
        view = client.create_table(view, exists_ok=True)    
        write_log("[{}] Created L0 view: {}", idx, l1_view_name)
        """
    else:
        return [view_dataset_id, bq_src_dataset_name, src_table_name, "", "오류 : 테이블이 존재하지 않습니다.", "오류 : 테이블이 존재하지 않습니다.", "", ""]

    # create or replace view (ST, L0)
    if bq_src_dataset_name[0:2] == 'L0':
        bq_create_st_view_query = bq_create_view_query_fmt.format(view_dataset_id, st_view_name, bq_st_view_query)
        try:
            query_job = client.query(bq_create_st_view_query)
            query_job.result()
        except Exception as e:
            print(e)

        bq_create_l0_view_query = bq_create_view_query_fmt.format(view_dataset_id, l0_view_name, bq_l0_view_query)
        try:
            query_job = client.query(bq_create_l0_view_query)
            query_job.result()
        except Exception as e:
            print(e)
    # create or replace view (L1, A1)
    else:
        bq_create_l1_view_query = bq_create_view_query_fmt.format(view_dataset_id, l1_view_name, bq_l1_view_query)
        try:
            query_job = client.query(bq_create_l1_view_query)
            query_job.result()
        except Exception as e:
            print(e)

    # grant authorized view (ST, L0)
    if bq_src_dataset_name[0:2] == 'L0':
        source_dataset_ref = client.get_dataset(bq_st_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        OB_ST_ACL_LIST = [entry.dataset.dataset_id for entry in access_entries if str(entry.dataset) != 'None']
        if view_dataset_id not in OB_ST_ACL_LIST:
            view_reference = {
                "projectId": project_id,
                "datasetId": view_dataset_id,
                "tableId": st_view_name,
            }
            add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
            access_entries.append(add_access_entry)
            source_dataset_ref.access_entries = access_entries
            try:
                source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
                write_log("[{}] Granted ST view access: {}=>{}", idx, bq_st_src_dataset_name, st_view_name)
            except Exception as e:
                print(e)
        else:
            write_log("[{}] OB_DATASET-{} Already in {} ACL List", idx, view_dataset_id, bq_st_src_dataset_name)

        source_dataset_ref = client.get_dataset(bq_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        OB_ACL_LIST = [entry.dataset.dataset_id for entry in access_entries if str(entry.dataset) != 'None']
        if view_dataset_id not in OB_ACL_LIST:
            view_reference = {
                "projectId": project_id,
                "datasetId": view_dataset_id,
                "tableId": l0_view_name,
            }
            add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
            access_entries.append(add_access_entry)
            source_dataset_ref.access_entries = access_entries
            try:
                source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
                write_log("[{}] Granted L0 view access: {}=>{}", idx, bq_src_dataset_name, l0_view_name)
            except Exception as e:
                print(e)
        else:
            write_log("[{}] OB_DATASET-{} Already in {} ACL List", idx, view_dataset_id, bq_src_dataset_name)

    # grant authorized view (L1)
    else:
        source_dataset_ref = client.get_dataset(bq_src_dataset_name)
        access_entries = source_dataset_ref.access_entries
        view_reference = {
            "projectId": project_id,
            "datasetId": view_dataset_id,
            "tableId": l1_view_name,
        }
        add_access_entry = bigquery.AccessEntry(None, "view", view_reference)
        access_entries.append(add_access_entry)
        source_dataset_ref.access_entries = access_entries
        try:
            source_dataset_ref = client.update_dataset(source_dataset_ref, ["access_entries"])
            write_log("[{}] Granted L1 view access: {}=>{}", idx, bq_src_dataset_name, l1_view_name)
        except Exception as e:
            print(e)

    write_log("[{}] View job done: {}.{}", idx, bq_src_dataset_name, src_table_name)

    return [view_dataset_id, bq_src_dataset_name, src_table_name, use_personal_info, l0_view_name, st_view_name,
              bq_l0_view_query, bq_st_view_query]


# 메인 함수
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-ix", "--input_xml", required=True, help="Input XML 파일")
    args = vars(ap.parse_args())

    sys.stdout = Logger()

    project_id = 'pj-lge-edl'
    mysql_conn_str = "mysql+pymysql://.....".format()

    # WHERE 조건 추가 (김현진C, 20/12/29)
    bq_view_query_fmt = 'SELECT {} FROM {}.{} WHERE {}'
    bq_view_except_pinfo_query_fmt = 'SELECT {} EXCEPT ({}) FROM {}.{} WHERE {}'
    bq_create_view_query_fmt = 'CREATE OR REPLACE VIEW {}.{} AS {}'

    try:
        output_xml = "ob_view_output.xml"
        with open(output_xml, 'w') as f:
            f.write("")

        input_tree = et.parse(args["input_xml"])
        input_root = input_tree.getroot()

        view_dataset_map = {}
        result_list = []

        client = bigquery.Client()
        edlpp_engine = create_engine(mysql_conn_str)

        for row in input_root.findall('Row'):

            try:
                input_view_dataset = row[0].text
                view_dataset_flag = False
                if input_view_dataset in view_dataset_map:
                    view_dataset_flag = view_dataset_map[input_view_dataset]
                else:
                    try:
                        view_dataset_ref = client.get_dataset(input_view_dataset)
                        view_dataset_flag = view_dataset_ref.dataset_id is not None
                    except NotFound:
                        write_log('View dataset not found: {}', input_view_dataset)

                    view_dataset_map[input_view_dataset] = view_dataset_flag

                if view_dataset_flag:
                    if row[5].text == 'N':
                        result_list.append(create_view_no_catalog(client, project_id, row, bq_view_query_fmt, bq_view_except_pinfo_query_fmt, bq_create_view_query_fmt))
                    else:
                        result_list.append(create_view_catalog(client, project_id, edlpp_engine, row, bq_view_query_fmt, bq_view_except_pinfo_query_fmt, bq_create_view_query_fmt))

            # except Exception as e:
            except NotFound as e:
                write_log('Create View Error : {}', str(e))


        if len(result_list) > 0:
            output_root = et.Element("Root")
            for items in result_list:
                print(items)
                row = et.SubElement(output_root, "Row")
                # output_root.append(row)
                for index, item in enumerate(items):
                    column = et.SubElement(row, "Column" + str(index + 1))
                    column.text = item
            tree = et.ElementTree(output_root)
            tree.write(output_xml)

    # except Exception as e:
    except NotFound as e:
        write_log('Process Error : {}', str(e))

if __name__ == "__main__":
    main()
