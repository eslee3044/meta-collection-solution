import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
import argparse

# 엑셀 연동하여 값 전달
ap = argparse.ArgumentParser()
ap.add_argument("-t", "--table", required=True, help="Table name (ex) IFS_VD_LINE_CAPACITY")
ap.add_argument("-s", "--system", required=True, help="SYSTEM CODE (ex) MDMS, GQMS, GERP ...")
ap.add_argument("-p", "--postfix", required=True, help="테이블 접미사")
ap.add_argument("-i", "--instance", required=False, help="INSTANCE_NAME (ex) APNGSFSP, LGNBHP ...")
ap.add_argument("-o", "--owner", required=True, help="Owner (ex) LGHIRUNP, XXPPS")
args = vars(ap.parse_args())

table_name = args["table"]
system = args["system"]
postfix = args["postfix"]
instance_nm = args["instance"]
owner_nm = args["owner"]

sqlquery = f"""   
 SELECT C.system_cd
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
    AND C.postfix = '{postfix}'
GROUP BY C.system_cd, T.database_name, C.owner, C.table_name, C.column_name,T.instance_name 
order by column_id
"""


# 테이블 정보 불러오기 위한 쿼리문

# oracle XML Property용 쿼리 추출
def oracle_stage_make_query(query_result,owner_nm):  # # ORACLE stage 일 때, 쿼리 뽑는 함수
  output = []
  rsltUptCols = []
  for row in query_result:
    column_name = row['column_name']
    table_name = row["table_name"]
    system_cd = row['system_cd'].rstrip('_')
    column_type = row['data_type'].lower()  
    update_base_col = row["update_base_yn"].lower()    # 24.10.22 이하늘 추가  ----

    if update_base_col == "y":
        rsltUptCols.append(row)  
    if len(rsltUptCols) > 0:
        update_col = rsltUptCols[0]["column_name"]   # -----

    if column_type in ('number', 'float', 'double', 'decimal', 'numeric'):
        output.append(f"ROUND({column_name}, 9) AS {column_name}")
    else:    
        output.append(f"{column_name}" )
  # query = f"SELECT {','.join(output)} from {table_name}"
  query = (
        "SELECT\n"
        " " +",\n    ".join(output) + "\n"
        "FROM " + owner_nm +"."+table_name + "\n"
        "WHERE " + update_col + " >= TO_DATE('#$P_BF1_BASE_DATE#','YYYYMMDD')" + "\n"
          "AND " + update_col + " < TO_DATE('#$P_BASE_DATE#','YYYYMMDD') + 1"
    )
  ora_xml_property = f"""
<?xml version='1.0' encoding='UTF-16'?><Properties version='1.1'><Common><Context type='int'>1</Context><Variant type='string'>11</Variant><DescriptorVersion type='string'>1.0</DescriptorVersion><PartitionType type='int'>-1</PartitionType><RCP type='int'>0</RCP></Common><Connection><Server modified='1' type='string'><![CDATA[#$S_{system_cd}#]]></Server><Username modified='1' type='string'><![CDATA[#$S_{system_cd}_USER#]]></Username><Password modified='1' type='string'><![CDATA[#$S_{system_cd}_PWD#]]></Password><OSLevelAuthentication type='bool'><![CDATA[0]]></OSLevelAuthentication><Version type='string'><![CDATA[11g]]></Version></Connection><Usage><ReadMode type='int'><![CDATA[0]]></ReadMode><GenerateSQL type='bool'><![CDATA[0]]></GenerateSQL><EnableQuotedIDs type='bool'><![CDATA[0]]></EnableQuotedIDs><SQL><SelectStatement modified='1' type='string'><![CDATA[{query}]]><ReadFromFileSelect type='bool'><![CDATA[0]]></ReadFromFileSelect></SelectStatement></SQL><EnablePartitionedReads collapsed='1' type='bool'><![CDATA[0]]></EnablePartitionedReads><Transaction><IsolationLevel type='int'><![CDATA[0]]></IsolationLevel><RecordCount type='int'><![CDATA[2000]]></RecordCount><EndOfWave type='int'><![CDATA[0]]></EndOfWave></Transaction><Session><ArraySize type='int'><![CDATA[2000]]></ArraySize><PrefetchRowCount type='int'><![CDATA[1]]></PrefetchRowCount><PrefetchMemorySize type='int'><![CDATA[0]]></PrefetchMemorySize><PassLobLocator collapsed='1' type='bool'><![CDATA[0]]></PassLobLocator><BFILEasBLOB type='bool'><![CDATA[0]]></BFILEasBLOB><TreatWarningsAsErrors type='bool'><![CDATA[0]]></TreatWarningsAsErrors><TreatFetchTruncateAsError type='bool'><![CDATA[1]]></TreatFetchTruncateAsError></Session><BeforeAfter collapsed='1' type='bool'><![CDATA[0]]></BeforeAfter><ApplicationFailoverControl collapsed='1' type='bool'><![CDATA[0]]></ApplicationFailoverControl><LimitRows collapsed='1' type='bool'><![CDATA[0]]></LimitRows></Usage></Properties>"""

  return ora_xml_property

# JDBC XML Property용 쿼리 추출
def jdbc_stage_make_query(query_result,owner_nm,db_type):   # JDBC stage 일 때, 쿼리 뽑는 함수
  output = []
  rsltUptCols = []
  for row in query_result:
    column_name = row['column_name']
    table_name = row["table_name"]
    system_cd = row['system_cd'].rstrip('_')
    column_type = row['data_type'].lower()  
    update_base_col = row["update_base_yn"].lower()    # 24.10.22 이하늘 추가  ----

    if update_base_col == "y":
        rsltUptCols.append(row)  
    if len(rsltUptCols) > 0:
        update_col = rsltUptCols[0]["column_name"]   # -----

    if db_type == 'postgresql':
        if column_type in ('double', 'double precision'):
            output.append(f"ROUND(CAST({column_name} AS numeric), 9) AS {column_name}")
        elif column_type in ('number', 'float', 'decimal', 'numeric'):
            output.append(f"ROUND({column_name}, 9) AS {column_name}")
        else:
            output.append(f"{column_name}")
    else:
        if column_type in ('number', 'float', 'double', 'decimal', 'numeric', 'double precision'):
            output.append(f"ROUND({column_name}, 9) AS {column_name}")
        else:
            output.append(f"{column_name}")

   #  if column_type in ('number', 'float', 'double', 'decimal', 'numeric','double precision'):
   #      output.append(f"ROUND({column_name}, 9) AS {column_name}")
   #  else:
   #      output.append(f"{column_name}")
#   query = f" {','.join(output)} from {table_name}"
  query = (
        "SELECT\n"
        " " +",\n    ".join(output) + "\n"
        "FROM " + owner_nm +"."+table_name  + "\n"
        "WHERE " + update_col + " >= TO_DATE('#$P_BF1_BASE_DATE#','YYYYMMDD')" + "\n"
          "AND " + update_col + " < TO_DATE('#$P_BASE_DATE#','YYYYMMDD') + 1"
    )
  jdbc_xml_property = f"""
<?xml version='1.0' encoding='UTF-16'?><Properties version='1.1'><Common><Context type='int'>1</Context><Variant type='string'>1.0</Variant><DescriptorVersion type='string'>1.0</DescriptorVersion><PartitionType type='int'>-1</PartitionType><RCP type='int'>0</RCP></Common><Connection><URL modified='1' type='string'><![CDATA[#$S_{system_cd}#]]></URL><Username modified='1' type='string'><![CDATA[#$S_{system_cd}_USER#]]></Username><Password modified='1' type='string'><![CDATA[#$S_{system_cd}_PWD#]]></Password></Connection><Usage><ReadMode type='int'><![CDATA[0]]></ReadMode><GenerateSQL modified='1' type='bool'><![CDATA[0]]></GenerateSQL><EnableQuotedIDs type='bool'><![CDATA[0]]></EnableQuotedIDs><SQL><SelectStatement modified='1' type='string'><![CDATA[ {query}]]><ReadFromFileSelect type='bool'><![CDATA[0]]></ReadFromFileSelect></SelectStatement><EnablePartitionedReads type='bool'><![CDATA[0]]></EnablePartitionedReads></SQL><Transaction><RecordCount type='int'><![CDATA[2000]]></RecordCount><IsolationLevel type='int'><![CDATA[0]]></IsolationLevel><AutocommitMode type='int'><![CDATA[0]]></AutocommitMode><EndOfWave type='int'><![CDATA[0]]></EndOfWave><BeginEnd collapsed='1' type='bool'><![CDATA[0]]></BeginEnd></Transaction><Session><ArraySize type='int'><![CDATA[1]]></ArraySize><FetchSize type='int'><![CDATA[0]]></FetchSize><ReportSchemaMismatch type='bool'><![CDATA[0]]></ReportSchemaMismatch><DefaultLengthForColumns type='int'><![CDATA[200]]></DefaultLengthForColumns><DefaultLengthForLongColumns type='int'><![CDATA[20000]]></DefaultLengthForLongColumns><FailOnTruncation type='bool'><![CDATA[1]]></FailOnTruncation><GenerateAllColumnsAsUnicode type='bool'><![CDATA[0]]></GenerateAllColumnsAsUnicode><CharacterSetForNonUnicodeColumns collapsed='1' type='int'><![CDATA[0]]></CharacterSetForNonUnicodeColumns><KeepConductorConnectionAlive type='bool'><![CDATA[1]]></KeepConductorConnectionAlive></Session><BeforeAfter collapsed='1' type='bool'><![CDATA[0]]></BeforeAfter><Java><ConnectorClasspath type='string'><![CDATA[$(DSHOME)/../DSComponents/bin/ccjdbc.jar;$(DSHOME)]]></ConnectorClasspath><Classpath type='string'><![CDATA[$(DSHOME)/../../ASBNode/lib/java/iis-shared.jar]]></Classpath><HeapSize type='int'><![CDATA[256]]></HeapSize><ConnectorOtherOptions type='string'><![CDATA[-Dcom.ibm.is.cc.options=noisfjars]]></ConnectorOtherOptions></Java><LimitRows collapsed='1' type='bool'><![CDATA[0]]></LimitRows></Usage></Properties>"""

  return jdbc_xml_property

# Source Column 정보 리스트 함수
def src_col_info_list(rsltCol):
    col_list_string = ""
    
    for row in rsltCol:
        S_COLUM_NM = row['column_name']
        S_DB_TYPE = row['database_name']
        S_TYPE_NM = row['data_type']
        S_NULL_YN = '0' if row["null_yn"] == 'N' else '1'
        S_TYPE_NM3 = S_TYPE_NM.upper()[:3]
        S_LENGTH_NO = int(row['data_length'])
        S_PK_KEY = '0' if row["pk_yn"] == 'N' else '1'
        S_DISP_NO = 0
        
        if S_TYPE_NM3 == "CHA" and S_TYPE_NM != "CHARACTER VARYING":
            S_TYPE_NO = 1
            S_SCALE_NO = 0
            S_DISP_NO = S_LENGTH_NO
        elif S_TYPE_NM3 in ["DEC", "NUM"]:
            S_TYPE_NO = 3
            S_LENGTH_NO = 38
            S_SCALE_NO = 10
            S_DISP_NO = int(S_LENGTH_NO) + 2
        elif S_TYPE_NM3 == "INT":
            S_TYPE_NO = 4
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM3 == "FLO":
            S_TYPE_NO = 6
            S_SCALE_NO = 0
            S_LENGTH_NO = 0
        elif S_TYPE_NM3 == "REA":
            S_TYPE_NO = 7
            S_SCALE_NO = 0
            S_LENGTH_NO = 0        
        elif S_TYPE_NM3 == "DOU":
            S_TYPE_NO = 8
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM3 == "DAT" and S_DB_TYPE != 'ORACLE':
            S_TYPE_NO = 9
            S_SCALE_NO = 0
            S_LENGTH_NO = 0
        elif S_TYPE_NM3 == "TIM" or (S_TYPE_NM3 == "DAT" and S_DB_TYPE == 'ORACLE') :
            S_TYPE_NO = 11
            S_SCALE_NO = 0
            S_DISP_NO = S_LENGTH_NO
        elif S_TYPE_NM3 == "VAR" or S_TYPE_NM == "CHARACTER VARYING":
            S_TYPE_NO = 12
            S_SCALE_NO = 0
            S_DISP_NO = 300 
            if S_LENGTH_NO >= 300:
               S_LENGTH_NO = S_LENGTH_NO
            else :
               S_LENGTH_NO = 300
        elif S_TYPE_NM3 == "BIT":
            S_TYPE_NO = -7
            S_SCALE_NO = 0
            S_LENGTH_NO = 0
        elif S_TYPE_NM3 == "TIN":
            S_TYPE_NO = -6
            S_SCALE_NO = 0
            S_LENGTH_NO = 0
            S_LENGTH_NO = 0
        elif S_TYPE_NM3 == "BIG":
            S_TYPE_NO = -5
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM == "LONGVARBINARY":
            S_TYPE_NO = -4
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM == "VARBINARY":
            S_TYPE_NO = -3
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM == "BINARY":
            S_TYPE_NO = -2
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM == "TEXT":
            S_TYPE_NO = -1
            S_SCALE_NO = 0
            S_DISP_NO = S_LENGTH_NO    	 	
        elif S_TYPE_NM3 == "LON":
            S_TYPE_NO = -10
            S_SCALE_NO = 0
            S_DISP_NO = 0
        elif S_TYPE_NM3 == "NVA":
            S_TYPE_NO = -9
            S_SCALE_NO = 0
        else:
            S_TYPE_NO = 12
            S_SCALE_NO = 0  
            S_DISP_NO = 0
        col_list = f"""
      BEGIN DSSUBRECORD
         Name "{S_COLUM_NM}"
         Description ""
         SqlType "{S_TYPE_NO}"
         Precision "{S_LENGTH_NO}"
         Scale "{S_SCALE_NO}"
         Nullable "{S_NULL_YN}"
         KeyPosition "{S_PK_KEY}"
         DisplaySize "{S_DISP_NO}"
         Group "0"
         SortKey "0"
         SortType "0"
         AllowCRLF "0"
         LevelNo "0"
         Occurs "0"
         PadNulls "0"
         SignOption "0"
         SortingOrder "0"
         ArrayHandling "0"
         SyncIndicator "0"
         PadChar ""
         ColumnReference "{S_COLUM_NM}"
         ExtendedPrecision "0"
         TaggedSubrec "0"
         OccursVarying "0"
         PKeyIsCaseless "0"
         SCDPurpose "0"
      END DSSUBRECORD
        """.strip()

        col_list_string += col_list + "\n      "
    return col_list_string

# Target Column 정보 리스트 함수
def tgt_col_info_list(rsltCol):
    col_list_string = ""

    for row in rsltCol:
        T_TABLE_NM = row["table_name"]
        T_DB_TYPE = row['database_name']
        T_COLUM_NM = row['column_name']
        T_TYPE_NM = row['data_type']
        T_NULL_YN = '0' if row["null_yn"] == 'N' else '1'
        T_TYPE_NM3 = T_TYPE_NM.upper()[:3]
        T_LENGTH_NO = int(row['data_length'])
        T_PK_KEY = '0' if row["pk_yn"] == 'N' else '1'
        T_DISP_NO = 0
        if T_TYPE_NM3 == "CHA" and T_TYPE_NM != "CHARACTER VARYING":
            T_TYPE_NO = 1
            T_SCALE_NO = 0
            T_DISP_NO = T_LENGTH_NO
        elif T_TYPE_NM3 in ["DEC", "NUM"]:
            T_TYPE_NO = 3
            T_LENGTH_NO = 38
            T_SCALE_NO = 10
            T_DISP_NO = int(T_LENGTH_NO) + 2
        elif T_TYPE_NM3 == "INT":
            T_TYPE_NO = 4
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM3 == "FLO":
            T_TYPE_NO = 6
            T_SCALE_NO = 0
            T_LENGTH_NO = 0
        elif T_TYPE_NM3 == "REA":
            T_TYPE_NO = 7
            T_SCALE_NO = 0
            T_LENGTH_NO = 0        
        elif T_TYPE_NM3 == "DOU":
            T_TYPE_NO = 8
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM3 == "DAT" and T_DB_TYPE != 'ORACLE':
            T_TYPE_NO = 9
            T_SCALE_NO = 0
            T_LENGTH_NO = 0
        elif T_TYPE_NM3 == "TIM" or (T_TYPE_NM3 == "DAT" and T_DB_TYPE == 'ORACLE') :
            T_TYPE_NO = 11
            T_SCALE_NO = 0
            T_DISP_NO = T_LENGTH_NO
        elif T_TYPE_NM3 == "VAR" or T_TYPE_NM == "CHARACTER VARYING":
            T_TYPE_NO = 12
            T_SCALE_NO = 0
            T_DISP_NO = 300 
            if T_LENGTH_NO >= 300:
               T_LENGTH_NO = T_LENGTH_NO
            else :
               T_LENGTH_NO = 300
        elif T_TYPE_NM3 == "BIT":
            T_TYPE_NO = -7
            T_SCALE_NO = 0
            T_LENGTH_NO = 0
        elif T_TYPE_NM3 == "TIN":
            T_TYPE_NO = -6
            T_SCALE_NO = 0
            T_LENGTH_NO = 0
            T_LENGTH_NO = 0
        elif T_TYPE_NM3 == "BIG":
            T_TYPE_NO = -5
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM == "LONGVARBINARY":
            T_TYPE_NO = -4
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM == "VARBINARY":
            T_TYPE_NO = -3
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM == "BINARY":
            T_TYPE_NO = -2
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM3 == "TEX":
            T_TYPE_NO = -1
            T_SCALE_NO = 0
            T_DISP_NO = T_LENGTH_NO    	 	
        elif T_TYPE_NM3 == "LON":
            T_TYPE_NO = -10
            T_SCALE_NO = 0
            T_DISP_NO = 0
        elif T_TYPE_NM3 == "NVA":
            T_TYPE_NO = -9
            T_SCALE_NO = 0
        else:
            T_TYPE_NO = 12
            T_SCALE_NO = 0
            T_DISP_NO = T_LENGTH_NO  

        col_list = f"""
      BEGIN DSSUBRECORD
         Name "{T_COLUM_NM}"
         Description ""
         SqlType "{T_TYPE_NO}"
         Precision "{T_LENGTH_NO}"
         Scale "{T_SCALE_NO}"
         Nullable "{T_NULL_YN}"
         KeyPosition "{T_PK_KEY}"
         DisplaySize "{T_DISP_NO}"
         Derivation "S_{T_TABLE_NM}.{T_COLUM_NM}"
         Group "0"
         ParsedDerivation "S_{T_TABLE_NM}.{T_COLUM_NM}"
         SourceColumn "S_{T_TABLE_NM}.{T_COLUM_NM}"
         SortKey "0"
         SortType "0"
         AllowCRLF "0"
         LevelNo "0"
         Occurs "0"
         PadNulls "0"
         SignOption "0"
         SortingOrder "0"
         ArrayHandling "0"
         SyncIndicator "0"
         PadChar ""
         ColumnReference "{T_COLUM_NM}"
         ExtendedPrecision "0"
         TaggedSubrec "0"
         OccursVarying "0"
         PKeyIsCaseless "0"
         SCDPurpose "0"
      END DSSUBRECORD
        """.strip()

        col_list_string += col_list + "\n      "
    return col_list_string

# Source 컬럼정보
def src_write_record(rsltCol):
    output = []

    for row in rsltCol:
        data_type = row['data_type']
        column_name = row['column_name']
        null_yn = 'nullable' if row['null_yn'] == 'Y' else ''
        data_len = int(row['data_length'])

        if data_type in ('VARCHAR2','VARCHAR',"LONGVARCHAR",'CHARACTER VARYING', ) :
            output.append(f'{column_name}:{null_yn} ustring[max={data_len}];')
        elif data_type == 'TEXT':
            output.append(f'{column_name}:{null_yn} ustring[];')
        elif data_type == 'TIMESTAMP':
            output.append(f'{column_name}:{null_yn} timestamp[microseconds];')
        elif data_type == 'DATE':
            output.append(f'{column_name}:{null_yn} date;')
        elif data_type in ('NUMBER', 'DECIMAL'):
            output.append(f'{column_name}:{null_yn} decimal[38,10];')
        elif data_type == 'INTEGER':
            output.append(f'{column_name}:{null_yn} int32;')
        elif data_type == 'BIGINT':
            output.append(f'{column_name}:{null_yn} int64;')
        elif data_type == 'DOUBLE':
            output.append(f'{column_name}:{null_yn} dfloat;')

        else:
            output.append(f'{column_name}:{null_yn} {data_type};')
    
    return "\n  ".join(output)

# header 작성
def fun1_head(file_obj):
    header_content = f"""
BEGIN HEADER
   CharacterSet "CP949"
   ExportingTool "IBM InfoSphere DataStage Export"
   ToolVersion "8"
   ServerName "VEDLETLP1"
   ToolInstanceID "DATALAKE"
   MDISVersion "1.0"
   Date "{datetime.today().strftime('%Y-%m-%d')}"
   Time "{datetime.now().strftime('%H.%M.%S')}"
   ServerVersion "11.7"
END HEADER


"""
    with open(file_obj, 'w', encoding='utf-8') as file_obj:
        file_obj.write(header_content.strip() + "\n")

#사전/사후
def fun2_param_start(file_obj,system, table_name):
    param_start_script = f"""
BEGIN DSJOB
   Identifier "s_m_{system}_{table_name}"
   DateModified "{datetime.today().strftime('%Y-%m-%d')}"
   TimeModified "{datetime.now().strftime('%H.%M.%S')}"
   BEGIN DSRECORD
      Identifier "ROOT"
      OLEType "CJobDefn"
      Readonly "0"
      Name "s_m_{system}_{table_name}"
      NextID "4"
      Container "V0"
      FullDescription =+=+=+=
Job ID         : s_m_{system}_{table_name}
Source Table   : {system}.{table_name}
Target Table   : ST_{system}.{table_name}
Editor         : hnlee
Created Date   : {datetime.today().strftime('%Y-%m-%d')}
Description    : L0_{system}.{table_name} \(BCC0)\(ACBD)\(C801)\(C7AC)

=+=+=+=

      JobVersion "56.0.0"
      BeforeSubr "DSU.TComScrRunGCP\\\\LB@BQ^DF^#$Table_Name#^#$Instance_Name#"
      AfterSubr "DSU.TComScrRunGCP\\\\BQ^D^#$Table_Name#^#$WHERE_STR#@BQ^BL^#$Table_Name#^#$Instance_Name#@BQ^BP^#$Table_Name#^#$Instance_Name#@BQ^DF^#$Table_Name#^#$Instance_Name#@LA"
"""
    with open(file_obj, 'a', encoding='utf-8') as file_obj:
        file_obj.write(param_start_script.strip() + "\n      ")

# 파라미터 작성 함수. 
def fun2_param_end(file_obj,system,table_name):
    param_end = f"""
      Parameters "CParameters"
      BEGIN DSSUBRECORD
         Name "$P_BF1_BASE_DATE"
         Prompt "Before 1 Date"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$P_BASE_DATE"
         Prompt "Base Date"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$DataSet"
         Prompt "BQ EDL Data Set"
         Default "ST_{system}"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$Table_Name"
         Prompt "BQ EDL Table Name"
         Default "{table_name}"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD	  
      BEGIN DSSUBRECORD
         Name "$Merge_Name"
         Prompt "BQ EDL Merge SP"
         Default "SP_MRG_$Table_Name"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$Instance_Name"
         Prompt "Instance Name"
         Default "N"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$S_{system}"
         Prompt "{system} SID"
         Default "$PROJDEF"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$S_{system}_USER"
         Prompt "{system} User"
         Default "$PROJDEF"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$S_{system}_PWD"
         Prompt "{system} Password"
         Default "{{iisenc}}awt4ggFyTBBA0zwUHYVnhp9elJdLyLC9kkMVo/t7LcPagl8F5oWGKoJ6zcD2YCnYe2YWz0I1A9kkEs9iLmw5S+BxX75GdfuNAKeRXGR1LiA="
         ParamType "1"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD	  
      BEGIN DSSUBRECORD
         Name "$BQ_KEY_EDL"
         Prompt "EDL Credential File"
         Default "$PROJDEF"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$BQ_BUCKET_EDL"
         Prompt "EDL Storage Path"
         Default "$PROJDEF"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "$WHERE_STR"
         Prompt "Where String"
         Default "P_PTT = CURRENT_DATE('Asia/Seoul')"
         ParamType "0"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD 
         Name "$APT_CONFIG_FILE"
         Prompt "Configuration file"
         Default "/engn001/IBM/InformationServer/Server/Configurations/default.apt"
         HelpTxt "The Parallel job configuration file."
         ParamType "4"
         ParamLength "0"
         ParamScale "0"
      END DSSUBRECORD
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "AdvancedRuntimeOptions"
         Value "#DSProjectARTOptions#"
      END DSSUBRECORD
"""
    with open(file_obj, 'a', encoding='utf-8') as file_obj:
        file_obj.write(param_end.strip() + "\n      ")

# 전체 property 및 시각적 객체 설정하는 곳. 카테고리 
# 테이블 이름 기준으로 S, T 네이밍, oracle, jdbc용 stage_db type
def fun3_Job_propt(file_obj,table_name, stage_db):
    job_propt_content = f"""
BEGIN DSSUBRECORD
         Owner "APT"
         Name "IdentList"
         Value "S_{table_name}|TR01|T_{table_name}" 
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "ClientCodePage"
         Value "949"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TraceMode"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TraceSeq"
         Value "1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TraceRecords"
         Value "100"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TraceSkip"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TracePeriod"
         Value "1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "RecordJobPerformanceData"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "MessageHandler"
         Value "EDW_MSG"
      END DSSUBRECORD
      NULLIndicatorPosition "0"
      IsTemplate "0"
      NLSLocale ",,,,"
      JobType "3"
      Category "\\\\Jobs\\\\98.INIT\\\\AUTO"
      CenturyBreakYear "30"
      NextAliasID "2"
      ParameterFileDDName "DD00001"
      ReservedWordCheck "1"
      TransactionSize "0"
      ValidationStatus "0"
      Uploadable "0"
      PgmCustomizationFlag "0"
      JobReportFlag "0"
      AllowMultipleInvocations "0"
      Act2ActOverideDefaults "0"
      Act2ActEnableRowBuffer "0"
      Act2ActUseIPC "0"
      Act2ActBufferSize "0"
      Act2ActIPCTimeout "0"
      ExpressionSemanticCheckFlag "0"
      TraceOption "0"
      EnableCacheSharing "0"
      RuntimeColumnPropagation "0"
      RelStagesInJobStatus "-1"
      WebServiceEnabled "0"
      MFProcessMetaData "0"
      MFProcessMetaDataXMLFileExchangeMethod "0"
      IMSProgType "0"
      CopyLibPrefix "ARDT"
      RecordPerformanceResults "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V0"
      OLEType "CContainerView"
      Readonly "0"
      Name "Job"
      NextID "1"
      IsTopLevel "0"
      StageList "V2A0|V0S17|V6S0|V0S27"
      StageXPos "1|192|552|960"
      StageYPos "2|264|264|264"
      StageTypes "ID_PALETTEJOBANNOTATION|CCustomStage.CC_GUI|CTransformerStage|CCustomStage.CC_GUI"
      NextStageID "28"
      SnapToGrid "1"
      GridLines "0"
      ZoomValue "100"
      StageXSize "470|41|48|48"
      StageYSize "112|53|48|48"
      ContainerViewSizing "0000 0023 1439 0694 0000 0001 0018 0000"
      StageNames " |S_{table_name}|TR01|T_{table_name}"
      StageTypeIDs " |{stage_db}|CTransformerStage|GoogleCloudStoragePX"  
      LinkNames " |S_{table_name}|T_{table_name}|"
      LinkHasMetaDatas " |True|True| "
      LinkTypes " |1|1| "
      LinkNamePositionXs " |324|704| "
      LinkNamePositionYs " |252|291| "
      TargetStageIDs " |V6S0|V0S27| "
      SourceStageEffectiveExecutionModes " |2|2| "
      SourceStageRuntimeExecutionModes " |2|2| "
      TargetStageEffectiveExecutionModes " |2|2| "
      TargetStageRuntimeExecutionModes " |2|2| "
      LinkIsSingleOperatorLookup " |False|False| "
      LinkIsSortSequential " |False|False| "
      LinkSortMode " |0|0| "
      LinkPartColMode " |1|1| "
      LinkSourcePinIDs " |V0S17P1|V6S0P3| "
   END DSRECORD
"""
    with open(file_obj, 'a', encoding='utf-8') as file_obj:
        file_obj.write(job_propt_content.strip() + "\n   ")

# Source stage 설정하는 곳. oracle
def fun4_src_stage_oracle(file_obj, table_name):
   src_attr_ora = f"""
   BEGIN DSRECORD
      Identifier "V0S17"
      OLEType "CCustomStage"
      Readonly "0"
      Name "S_{table_name}"
      NextID "2"
      OutputPins "V0S17P1"
      StageType "OracleConnectorPX"
      AllowColumnMapping "0"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "11"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "ccora11g"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariants"
         Value "V1;11:\\"11g\\":ccora11g;12:\\"12c\\":ccora12c"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsLibraries"
         Value "ccora11g,ccora12c"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsVersions"
         Value "1.0,1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Orientation"
         Value "link"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "OracleConnector"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Engine"
         Value "EE"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Context"
         Value "source"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectionString"
         Value "/Connection/Server"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Username"
         Value "/Connection/Username"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Password"
         Value "/Connection/Password"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RACName"
         Value "/Connection/RACName"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "xaoDbName"
         Value "/Connection/xaoDbName"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "OSLevelAuthentication"
         Value "/Connection/OSLevelAuthentication"
      END DSSUBRECORD
"""
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
        file_obj.write(src_attr_ora.strip() + "\n      ")

# Source stage 설정하는 곳. JDBC
def fun4_src_stage_jdbc(file_obj, table_name): #  O(오라클 O, jdbc O)
   src_attr_jdbc = f"""
   BEGIN DSRECORD
      Identifier "V0S17"
      OLEType "CCustomStage"
      Readonly "0"
      Name "S_{table_name}"
      NextID "2"
      OutputPins "V0S17P1"
      StageType "JDBCConnectorPX"
      AllowColumnMapping "0"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "\\"java:com/ibm/is/cc/jdbc/CC_JDBCConnectorLibrary,$(DSHOME)/../DSComponents/bin/ccjdbc.jar;$(DSHOME)\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariants"
         Value "V1;1.0::\\"java:com/ibm/is/cc/jdbc/CC_JDBCConnectorLibrary,$(DSHOME)/../DSComponents/bin/ccjdbc.jar;$(DSHOME)\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsLibraries"
         Value "\\"java:com/ibm/is/cc/jdbc/CC_JDBCConnectorLibrary,$(DSHOME)/../DSComponents/bin/ccjdbc.jar;$(DSHOME)\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsVersions"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Orientation"
         Value "link"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "JDBCConnector"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Engine"
         Value "EE"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Context"
         Value "source"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectionString"
         Value "/Connection/URL"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Username"
         Value "/Connection/Username"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Password"
         Value "/Connection/Password"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Attributes"
         Value "/Connection/Attributes"
      END DSSUBRECORD
"""
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
        file_obj.write(src_attr_jdbc.strip() + "\n      ")

# Source 쿼리 xml 설정하는 곳
def fun5_src_xml_oracle(file_obj,table_name,rsltCol,owner_nm ):   
      xml_pro = f'''  
      BEGIN DSSUBRECORD
         Name "XMLProperties"
         Value =+=+=+={oracle_stage_make_query(rsltCol,owner_nm)}
=+=+=+=
      END DSSUBRECORD
      NextRecordID "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V0S17P1"
      OLEType "CCustomOutput"
      Readonly "0"
      Name "S_{table_name}"
      Partner "V6S0|V6S0P4"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "lookup\\\\type"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "11"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "ccora11g"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "OracleConnector"
      END DSSUBRECORD
'''   
      with open(file_obj, 'a', encoding='utf-8') as file_obj:
         file_obj.write(xml_pro.strip() + "\n      ")

# Source 쿼리 xml 설정하는 곳
def fun5_src_xml_jdbc(file_obj,table_name,rsltCol,owner_nm,db_type ):   
      xml_pro = f'''  
      BEGIN DSSUBRECORD
         Name "XMLProperties"
         Value =+=+=+={jdbc_stage_make_query(rsltCol, owner_nm,db_type)}
=+=+=+=
      END DSSUBRECORD
      NextRecordID "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V0S17P1"
      OLEType "CCustomOutput"
      Readonly "0"
      Name "S_{table_name}"
      Partner "V6S0|V6S0P4"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "\\"java:com/ibm/is/cc/jdbc/CC_JDBCConnectorLibrary,$(DSHOME)/../DSComponents/bin/ccjdbc.jar;$(DSHOME)\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "JDBCConnector"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "lookup\\\\type"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD'''   
      with open(file_obj, 'a', encoding='utf-8') as file_obj:
         file_obj.write(xml_pro.strip() + "\n      ")

# Source Output 부분.
# 컬럼 불러오기. advanced 설정
def fun6_src_record(file_obj, rsltCol):   
      record_write = f""" 
Columns "COutputColumn"
      {src_col_info_list(rsltCol)}
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "DiskWriteInc"
         Value "1048576"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "BufFreeRun"
         Value "50"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "MaxMemBufSize"
         Value "3145728"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "QueueUpperSize"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "SchemaFormat"
      END DSSUBRECORD
      LeftTextPos "324"
      TopTextPos "252"
      LinkMinimised "0"
   END DSRECORD
      """
      with open(file_obj, 'a', encoding='utf-8') as file_obj:
         file_obj.write(record_write.strip() + "\n")

# Target(GCS) stage 설정하는 곳/ oracle, jdbc 모두 고정
def fun7_tgt_stage(file_obj,table_name):   
   tgt_view = f"""
   BEGIN DSRECORD
      Identifier "V0S27"
      OLEType "CCustomStage"
      Readonly "0"
      Name "T_{table_name}"
      NextID "2"
      InputPins "V0S27P1"
      StageType "GoogleCloudStoragePX"
      AllowColumnMapping "0"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "\\"java:com/ibm/iis/cc/googlecloudstorage/GoogleCloudStorageLibrary,$(DSHOME)/../DSComponents/bin/ccscapi.jar;$(DSHOME)/../DSComponents/bin/ccgooglecloudstorage.jar;$(DSHOME)/../DSComponents/bin/ccapi.jar;$(DSHOME)/../DSComponents/bin/ccjava-api.jar;$(DSHOME)/../DSComponents/bin/ccjava.jar;$(DSHOME)/../DSComponents/bin/JISDocHandler.jar;$(DSHOME)/../DSComponents/bin/thirdparty;$(DSHOME)/../DSComponents/bin/scapi;$(DSHOME);\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariants"
         Value "V1;1.0::\\"java:com/ibm/iis/cc/googlecloudstorage/GoogleCloudStorageLibrary,$(DSHOME)/../DSComponents/bin/ccscapi.jar;$(DSHOME)/../DSComponents/bin/ccgooglecloudstorage.jar;$(DSHOME)/../DSComponents/bin/ccapi.jar;$(DSHOME)/../DSComponents/bin/ccjava-api.jar;$(DSHOME)/../DSComponents/bin/ccjava.jar;$(DSHOME)/../DSComponents/bin/JISDocHandler.jar;$(DSHOME)/../DSComponents/bin/thirdparty;$(DSHOME)/../DSComponents/bin/scapi;$(DSHOME);\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsLibraries"
         Value "\\"java:com/ibm/iis/cc/googlecloudstorage/GoogleCloudStorageLibrary,$(DSHOME)/../DSComponents/bin/ccscapi.jar;$(DSHOME)/../DSComponents/bin/ccgooglecloudstorage.jar;$(DSHOME)/../DSComponents/bin/ccapi.jar;$(DSHOME)/../DSComponents/bin/ccjava-api.jar;$(DSHOME)/../DSComponents/bin/ccjava.jar;$(DSHOME)/../DSComponents/bin/JISDocHandler.jar;$(DSHOME)/../DSComponents/bin/thirdparty;$(DSHOME)/../DSComponents/bin/scapi;$(DSHOME);\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "SupportedVariantsVersions"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Orientation"
         Value "stage"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "GoogleCloudStorage"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Engine"
         Value "EE"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "Context"
         Value "target"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "credentials_file"
         Value "/Connection/credentials_file"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "XMLProperties"
         Value "<?xml version='1.0' encoding='UTF-16'?><Properties version='1.1'><Common><Context type='int'>2</Context><Variant type='string'>1.0</Variant><DescriptorVersion type='string'>1.0</DescriptorVersion><PartitionType type='int'>-1</PartitionType><RCP type='int'>0</RCP></Common><Connection><credentials_file modified='1' type='string'><![CDATA[#$BQ_KEY_EDL#]]></credentials_file></Connection><Usage><bucket modified='1' type='string'><![CDATA[#$BQ_BUCKET_EDL#]]></bucket><create_bucket type='bool'><![CDATA[0]]></create_bucket><write_mode modified='1' type='int'><![CDATA[0]]></write_mode><file_name modified='1' type='string'><![CDATA[#$DataSet#.#$Table_Name#.#$Instance_Name#]]></file_name><file_format modified='1' type='int'><![CDATA[1]]></file_format><partitioned collapsed='1' type='bool'><![CDATA[0]]></partitioned><WaveHandling><AppendUID modified='1' type='bool'><![CDATA[0]]></AppendUID></WaveHandling><DelimitedSyntax><first_line_header collapsed='1' type='bool'><![CDATA[0]]></first_line_header><encoding type='string'><![CDATA[utf-8]]></encoding><create_bigquery_table collapsed='1' type='bool'><![CDATA[0]]></create_bigquery_table></DelimitedSyntax><connector_name type='string'><![CDATA[googlecloudstorage]]></connector_name><node_number type='int'><![CDATA[0]]></node_number><node_count type='int'><![CDATA[1]]></node_count><Java><HeapSize type='int'><![CDATA[256]]></HeapSize><ConnectorClasspath type='string'><![CDATA[$(DSHOME)/../DSComponents/bin/ccscapi.jar;$(DSHOME)/../DSComponents/bin/ccgooglecloudstorage.jar;$(DSHOME)/../DSComponents/bin/ccapi.jar;$(DSHOME)/../DSComponents/bin/ccjava-api.jar;$(DSHOME)/../DSComponents/bin/ccjava.jar;$(DSHOME)/../DSComponents/bin/JISDocHandler.jar;$(DSHOME)/../DSComponents/bin/thirdparty;$(DSHOME)/../DSComponents/bin/scapi]]></ConnectorClasspath><ConnectorOtherOptions type='string'><![CDATA[-Dcom.ibm.tools.attach.enable=no -Dcom.ibm.is.cc.options=noisfjars]]></ConnectorOtherOptions></Java><UserClassName type='string'><![CDATA[com.ibm.iis.cc.googlecloudstorage.GoogleCloudStorage]]></UserClassName></Usage></Properties >"
      END DSSUBRECORD
      NextRecordID "0"
   END DSRECORD
"""
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
      file_obj.write("   " + tgt_view.strip() + "\n")

# TR 스테이지 설정
def fun8_tr_stage(file_obj,table_name):    
      tgt_info = f'''   
BEGIN DSRECORD
      Identifier "V0S27P1"
      OLEType "CCustomInput"
      Readonly "0"
      Name "T_{table_name}"
      Partner "V6S0|V6S0P3"
      LinkType "1"
      ConditionNotMet "fail"
      LookupFail "fail"
      Properties "CCustomProperty"
      BEGIN DSSUBRECORD
         Name "VariantName"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantLibrary"
         Value "\\"java:com/ibm/iis/cc/googlecloudstorage/GoogleCloudStorageLibrary,$(DSHOME)/../DSComponents/bin/ccscapi.jar;$(DSHOME)/../DSComponents/bin/ccgooglecloudstorage.jar;$(DSHOME)/../DSComponents/bin/ccapi.jar;$(DSHOME)/../DSComponents/bin/ccjava-api.jar;$(DSHOME)/../DSComponents/bin/ccjava.jar;$(DSHOME)/../DSComponents/bin/JISDocHandler.jar;$(DSHOME)/../DSComponents/bin/thirdparty;$(DSHOME)/../DSComponents/bin/scapi;$(DSHOME);\\""
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "VariantVersion"
         Value "1.0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectFromLink"
         Value "-1"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectThreshold"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectNumber"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "RejectUsesPercentage"
         Value "false"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ConnectorName"
         Value "GoogleCloudStorage"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "XMLProperties"
         Value "<?xml version='1.0' encoding='UTF-16'?><Properties version='1.1'><Common><Context type='int'>2</Context><Variant type='string'>1.0</Variant><DescriptorVersion type='string'>1.0</DescriptorVersion><PartitionType type='int'>-1</PartitionType><RCP type='int'>0</RCP><Reject></Reject></Common><Usage></Usage></Properties >"
      END DSSUBRECORD
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "RTColumnProp"
         Value "0"
      END DSSUBRECORD
      TransactionSize "0"
      TXNBehaviour "40"
      EnableTxGroup "0"
      LinkMinimised "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V2A0"
      OLEType "CAnnotation"
      Readonly "0"
      Name "V2A0"
      NextID "0"
      AnnotationType "2"
      TextFont "\\(B3CB)\\(C6C0)\\(CCB4)\\\\10\\\\0\\\\0\\\\0\\\\400\\\\129"
      TextHorizontalJustification "0"
      TextVerticalJustification "0"
      TextColor "0"
      BackgroundColor "12713983"
      BackgroundTransparent "0"
      BorderVisible "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V6S0"
      OLEType "CTransformerStage"
      Readonly "0"
      Name "TR01"
      NextID "5"
      InputPins "V6S0P4"
      OutputPins "V6S0P3"
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TrxGenCode"
         Value =+=+=+=
//
// Generated file to implement the V6S0_s_m_GERP_{table_name}_TR01 transform operator.
//\n

// define our input/output link names
inputname 0 S_{table_name};
outputname 0 T_{table_name}; \n

global {{
 ustring DSJobStartTimestamp;
}}\n

initialize {{
 // define our control variables
 int8 RowRejected0;
 int8 NullSetVar0;\n

 // declare our intermediate variables for this section (1)
 int8 InterVar0_0;
 ustring InterVar0_1;
 string InterVar0_3;
 string InterVar0_6;\n

 // initialise constant values which require conversion
 InterVar0_0 = 9;
 InterVar0_1 = " ";
 InterVar0_3 = "%yyyy-%mm-%dd %h:%nn:%ss";
 InterVar0_6 = " ";
 // Stage variable declaration and initialisation
 timestamp StageVar0_UTCLOADTS;
 StageVar0_UTCLOADTS = timestamp_from_string("2001-01-01 00:00:01");
}}\n

mainloop {{\n

 // declare our intermediate variables for this section (2)
 ustring InterVar0_2;
 ustring InterVar0_4;
 string InterVar0_5;
 string InterVar0_7;\n

 // evaluate the stage variables first
 if ((hours_from_time(time_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp))) >= InterVar0_0)) {{
  InterVar0_2 = hours_from_time(time_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp))) - 9;
  InterVar0_4 = u_right_substring(string_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp) , InterVar0_3) , 6);
  StageVar0_UTCLOADTS = timestamp_from_ustring((((ustring_from_date(date_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp))) + InterVar0_1) + InterVar0_2) + InterVar0_4) , InterVar0_3);
 }} else {{
  InterVar0_5 = DSJobStartTimestamp;
  InterVar0_7 = hours_from_time(time_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp))) + 15;
  StageVar0_UTCLOADTS = timestamp_from_string((((string_from_date(date_from_days_since(-1 , InterVar0_5)) + InterVar0_6) + InterVar0_7) + right_substring(string_from_timestamp(timestamp_from_ustring(DSJobStartTimestamp) , InterVar0_3) , 6)) , InterVar0_3);
 }}
 //;\n

// initialise the rejected row variable
 RowRejected0 = 1;\n

 // evaluate columns (no constraints) for link: T_{table_name}
 T_{table_name}.P_PTT = current_date();
 T_{table_name}.ETL_LOAD_TS = StageVar0_UTCLOADTS;
 writerecord 0;
 RowRejected0 = 0;
}}\n

finish {{
}}\n

=+=+=+=
      END DSSUBRECORD
'''
      with open(file_obj, 'a', encoding='utf-8') as file_obj:
         file_obj.write("   " + tgt_info.strip() + "\n")

# TR 컬럼 설정
def fun9_tr_col(file_obj,system,table_name):  
   tgt2_stage = f"""
BEGIN DSSUBRECORD
         Owner "APT"
         Name "TrxGenCache"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TrxClassName"
         Value "V3S1_s_m_{system}_{table_name}_TR01"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "TrxGenWarnings"
         Value =+=+=+=
TR01
   WARNING: Error in Stage Variable derivation expression for variable UTCLOADTS. 
       - potential data or precision loss converting from int32 to int8

=+=+=+=
      END DSSUBRECORD
      ValidationStatus "0"
      StageType "CTransformerStage"
      BlockSize "0"
      SKKeySourceType "file"
      StageVars "CStageVar"
      BEGIN DSSUBRECORD
         Name "UTCLOADTS"
         Expression =+=+=+=
If HoursFromTime(TimestampToTime(DSJobStartTimestamp)) >= 9 
then StringToTimestamp(TimestampToDate(DSJobStartTimestamp) : " " : HoursFromTime(TimestampToTime(DSJobStartTimestamp)) - 9 : 
Right(TimestampToString(DSJobStartTimestamp, "%yyyy-%mm-%dd %h:%nn:%ss"), 6), "%yyyy-%mm-%dd %h:%nn:%ss") 
else StringToTimestamp(DateFromDaysSince(-1, DSJobStartTimestamp) : " " : HoursFromTime(TimestampToTime(DSJobStartTimestamp)) + 15 : 
Right(TimestampToString(DSJobStartTimestamp, "%yyyy-%mm-%dd %h:%nn:%ss"), 6), "%yyyy-%mm-%dd %h:%nn:%ss")
=+=+=+=
         SqlType "11"
         ParsedExpression " If HoursFromTime(TimestampToTime(DSJobStartTimestamp)) >= 9 then StringToTimestamp(TimestampToDate(DSJobStartTimestamp) : \\" \\" : HoursFromTime(TimestampToTime(DSJobStartTimestamp)) - 9 : Right(TimestampToString(DSJobStartTimestamp, \\"%yyyy-%mm-%dd %h:%nn:%ss\\"), 6), \\"%yyyy-%mm-%dd %h:%nn:%ss\\") else StringToTimestamp(DateFromDaysSince(-1, DSJobStartTimestamp) : \\" \\" : HoursFromTime(TimestampToTime(DSJobStartTimestamp)) + 15 : Right(TimestampToString(DSJobStartTimestamp, \\"%yyyy-%mm-%dd %h:%nn:%ss\\"), 6), \\"%yyyy-%mm-%dd %h:%nn:%ss\\")"
         Precision "255"
         ColScale "0"
         ExtendedPrecision "0"
      END DSSUBRECORD
      StageVarsMinimised "0"
      LoopVarsMaximised "0"
      MaxLoopIterations "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V6S0P3"
      OLEType "CTrxOutput"
      Readonly "0"
      Name "T_{table_name}"
      Partner "V0S27|V0S27P1"
      Reject "0"
      ErrorPin "0"
      RowLimit "0"
"""
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
      file_obj.write("      " + tgt2_stage.strip() + "\n")

# Target 컬럼정보 
# P_PTT, ETL_LOAD_TS 추가 후 원천 컬럼 정보 삽입
def fun10_tgt_column(file_obj,rsltCol):  
   tgr_record = f"""
Columns "COutputColumn"
      BEGIN DSSUBRECORD 
         Name "P_PTT"
         SqlType "9"
         Precision "0"
         Scale "0"
         Nullable "1"
         KeyPosition "0"
         DisplaySize "0"
         Derivation "CurrentDate()"
         Group "0"
         ParsedDerivation "CurrentDate()"
         SortKey "0"
         SortType "0"
         AllowCRLF "0"
         LevelNo "0"
         Occurs "0"
         PadNulls "0"
         SignOption "0"
         SortingOrder "0"
         ArrayHandling "0"
         SyncIndicator "0"
         PadChar ""
         ExtendedPrecision "0"
         TaggedSubrec "0"
         OccursVarying "0"
         PKeyIsCaseless "0"
         SCDPurpose "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Name "ETL_LOAD_TS"
         SqlType "11"
         Precision "0"
         Scale "0"
         Nullable "1"
         KeyPosition "0"
         DisplaySize "0"
         Derivation "UTCLOADTS"
         Group "0"
         ParsedDerivation "UTCLOADTS"
         SortKey "0"
         SortType "0"
         AllowCRLF "0"
         LevelNo "0"
         Occurs "0"
         PadNulls "0"
         SignOption "0"
         SortingOrder "0"
         StageVars "UTCLOADTS"
         ArrayHandling "0"
         SyncIndicator "0"
         PadChar ""
         ExtendedPrecision "1"
         TaggedSubrec "0"
         OccursVarying "0"
         PKeyIsCaseless "0"
         SCDPurpose "0"
      END DSSUBRECORD
      {tgt_col_info_list(rsltCol)}
"""
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
      file_obj.write("      " + tgr_record.strip() + "\n")

# Target advanced 설정
def fun11_tgt_advanced(file_obj): #O
   tgt_property = f"""
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "DiskWriteInc"
         Value "1048576"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "BufFreeRun"
         Value "50"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "MaxMemBufSize"
         Value "3145728"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "QueueUpperSize"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "Schema"
         Value =+=+=+=
      """
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
      file_obj.write("      " + tgt_property.strip() + "\n")

# Source, Target 컬럼 정보
def fun12_record_info(file_obj,table_name,rsltCol):   # 원천, gcs 행정보, db 읽어서 원천 가져오고 P_PTT, ETL_LOAD_TS 추가
   record_info = f"""
record
(
  P_PTT:nullable date;
  ETL_LOAD_TS:nullable timestamp[microseconds];
  {src_write_record(rsltCol)}
)
=+=+=+=
      END DSSUBRECORD
      LeftTextPos "704"
      TopTextPos "291"
      LinkMinimised "0"
   END DSRECORD
   BEGIN DSRECORD
      Identifier "V6S0P4"
      OLEType "CTrxInput"
      Readonly "0"
      Name "S_{table_name}"
      Partner "V0S17|V0S17P1"
      LinkType "1"
      MetaBag "CMetaProperty"
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "RTColumnProp"
         Value "0"
      END DSSUBRECORD
      BEGIN DSSUBRECORD
         Owner "APT"
         Name "Schema"
         Value =+=+=+=
record
(
   {src_write_record(rsltCol)}
)
=+=+=+=
      END DSSUBRECORD
      MultiRow "0"
      LinkMinimised "0"
   END DSRECORD
END DSJOB
""" 
   with open(file_obj, 'a', encoding='utf-8') as file_obj:
      file_obj.write("" + record_info.strip() + "\n")


def main():
   conn = psycopg2.connect(host='', user='', password='', dbname='')
   curs = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

   curs.execute(sqlquery)
   rsltCol = curs.fetchall()

   for row in rsltCol:
      db_type = row["database_name"].lower()  

   dsx_file = f"ds_job/{table_name}.dsx"

   fun1_head(dsx_file)
   fun2_param_start(dsx_file, system, table_name)
   fun2_param_end(dsx_file, system, table_name)

   if db_type == "oracle":
       fun3_Job_propt(dsx_file, table_name, "OracleConnectorPX")
       fun4_src_stage_oracle(dsx_file, table_name)
       fun5_src_xml_oracle(dsx_file, table_name, rsltCol, owner_nm)
   else:
       fun3_Job_propt(dsx_file, table_name, "JDBCConnectorPX")
       fun4_src_stage_jdbc(dsx_file, table_name)
       fun5_src_xml_jdbc(dsx_file, table_name, rsltCol, owner_nm, db_type)

   fun6_src_record(dsx_file, rsltCol)
   fun7_tgt_stage(dsx_file, table_name)
   fun8_tr_stage(dsx_file, table_name)
   fun9_tr_col(dsx_file, system, table_name)
   fun10_tgt_column(dsx_file, rsltCol)
   fun11_tgt_advanced(dsx_file)
   fun12_record_info(dsx_file, table_name, rsltCol)

if __name__ == "__main__":
    main()
       