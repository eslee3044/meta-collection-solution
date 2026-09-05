import os
import xml.etree.ElementTree as ET
import argparse
import pymysql
from myMap import *
from xml.sax.saxutils import escape
import uuid

# txtt.py -t OE_ORDER_HEADERS_ALL -s GERP -l I

###############################################################################
# 				genExtensionStr FUNCTION
###############################################################################    
def genExtensionStr(dsNm, tabNm, tgtFields):
	extStr = """<?xml version="1.0" encoding="UTF-8"?>
<imx:IMX xmlns:imx="http://com.informatica.imx" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" serializationSpecVersion="13.0" crcEnabled="0" xmlns:container="http://com.informatica.adapter.sdkadapter.patternblocks.container/2" versioncontainer="2.2.1" xmlns:metadata="http://com.infa.adapter.bigquery.table.metadata/1" versionmetadata="1.0.0" xmlns:asoextension="http://com.informatica.adapter.sdkadapter.asoextension/2" versionasoextension="2.4.0" xmlns:catalog="http://com.informatica.adapter.sdkadapter.patternblocks.catalog/2" versioncatalog="2.2.0" xmlns:flatrecord="http://com.informatica.adapter.sdkadapter.patternblocks.flatrecord/2" versionflatrecord="2.2.0" xmlns:typelibrary="http://com.informatica.metadata.common.typesystem.typelibrary/2" versiontypelibrary="2.5.0" xmlns:datasourceoperation="http://com.informatica.metadata.common.datasourceoperation/2" versiondatasourceoperation="2.6.1" xmlns:capability="http://com.infa.adapter.bigquery.table.runtime.capability/1" versioncapability="1.0.0" xmlns:sourceoperation="http://com.informatica.adapter.sdkadapter.projection.sourceoperation/2" versionsourceoperation="2.3.0" xmlns:connectinfo="http://com.informatica.metadata.common.connectinfo/2" versionconnectinfo="2.4.0" xmlns:sdkadapter="http://com.informatica.metadata.infasdk.connectinfo.sdkadapter/2" versionsdkadapter="2.1.0" xmlns:asoconfig="http://com.informatica.adapter.sdkadapter.asoconfig/2" versionasoconfig="2.3.0" xmlns:connection="http://com.infa.adapter.bigquery.connection/1" versionconnection="1.0.0" xmlns:projection="http://com.informatica.adapter.sdkadapter.projection/2" versionprojection="2.4.0" xmlns:modelextension="http://com.informatica.metadata.common.modelextension/2" versionmodelextension="2.1.0" xmlns:types="http://com.informatica.metadata.common.types/2" versiontypes="2.4.0" xmlns:adapter="http://com.informatica.metadata.common.adapter/2" versionadapter="2.2.0" xmlns:sdkmodelextension="http://com.informatica.metadata.infasdk.connectinfo.common.sdkmodelextension/1" versionsdkmodelextension="1.1.0" xmlns:logical="http://com.informatica.adapter.sdkadapter.logical/2" versionlogical="2.8.4" xmlns:conversionoperation="http://com.informatica.adapter.sdkadapter.projection.conversionoperation/2" versionconversionoperation="2.2.0" xmlns:core="http://com.informatica.metadata.common.core/2" versioncore="2.2.1" xmlns:field="http://com.informatica.adapter.sdkadapter.patternblocks.field/2" versionfield="2.2.0" xmlns:datasource="http://com.informatica.metadata.common.datasource/2" versiondatasource="2.2.0" xmlns:dsoconfig="http://com.informatica.metadata.common.dsoconfig/2" versiondsoconfig="2.1.0" xmlns:aso1="http://com.infa.adapter.bigquery.runtime.aso/1" versionaso1="1.0.0" xmlns:aso="http://com.informatica.adapter.sdkadapter.aso/2" versionaso="2.13.1" xmlns:typesystem="http://com.informatica.metadata.common.typesystem/2" versiontypesystem="2.2.0" xmlns:capabilityattribute="http://com.informatica.adapter.sdkadapter.capabilityattribute/2" versioncapabilityattribute="2.3.0" xmlns:sinkoperation="http://com.informatica.adapter.sdkadapter.projection.sinkoperation/2" versionsinkoperation="2.4.0" xsi:schemaLocation="http://com.informatica.imx IMX.xsd http://com.informatica.adapter.sdkadapter.patternblocks.container/2 com.informatica.adapter.sdkadapter.patternblocks.container.xsd http://com.infa.adapter.bigquery.table.metadata/1 com.infa.adapter.bigquery.table.metadata.xsd http://com.informatica.adapter.sdkadapter.asoextension/2 com.informatica.adapter.sdkadapter.asoextension.xsd http://com.informatica.adapter.sdkadapter.patternblocks.catalog/2 com.informatica.adapter.sdkadapter.patternblocks.catalog.xsd http://com.informatica.adapter.sdkadapter.patternblocks.flatrecord/2 com.informatica.adapter.sdkadapter.patternblocks.flatrecord.xsd http://com.informatica.metadata.common.typesystem.typelibrary/2 com.informatica.metadata.common.typesystem.typelibrary.xsd http://com.informatica.metadata.common.datasourceoperation/2 com.informatica.metadata.common.datasourceoperation.xsd http://com.infa.adapter.bigquery.table.runtime.capability/1 com.infa.adapter.bigquery.table.runtime.capability.xsd http://com.informatica.adapter.sdkadapter.projection.sourceoperation/2 com.informatica.adapter.sdkadapter.projection.sourceoperation.xsd http://com.informatica.metadata.common.connectinfo/2 com.informatica.metadata.common.connectinfo.xsd http://com.informatica.metadata.infasdk.connectinfo.sdkadapter/2 com.informatica.metadata.infasdk.connectinfo.sdkadapter.xsd http://com.informatica.adapter.sdkadapter.asoconfig/2 com.informatica.adapter.sdkadapter.asoconfig.xsd http://com.infa.adapter.bigquery.connection/1 com.infa.adapter.bigquery.connection.xsd http://com.informatica.adapter.sdkadapter.projection/2 com.informatica.adapter.sdkadapter.projection.xsd http://com.informatica.metadata.common.modelextension/2 com.informatica.metadata.common.modelextension.xsd http://com.informatica.metadata.common.types/2 com.informatica.metadata.common.types.xsd http://com.informatica.metadata.common.adapter/2 com.informatica.metadata.common.adapter.xsd http://com.informatica.metadata.infasdk.connectinfo.common.sdkmodelextension/1 com.informatica.metadata.infasdk.connectinfo.common.sdkmodelextension.xsd http://com.informatica.adapter.sdkadapter.logical/2 com.informatica.adapter.sdkadapter.logical.xsd http://com.informatica.adapter.sdkadapter.projection.conversionoperation/2 com.informatica.adapter.sdkadapter.projection.conversionoperation.xsd http://com.informatica.metadata.common.core/2 com.informatica.metadata.common.core.xsd http://com.informatica.adapter.sdkadapter.patternblocks.field/2 com.informatica.adapter.sdkadapter.patternblocks.field.xsd http://com.informatica.metadata.common.datasource/2 com.informatica.metadata.common.datasource.xsd http://com.informatica.metadata.common.dsoconfig/2 com.informatica.metadata.common.dsoconfig.xsd http://com.infa.adapter.bigquery.runtime.aso/1 com.infa.adapter.bigquery.runtime.aso.xsd http://com.informatica.adapter.sdkadapter.aso/2 com.informatica.adapter.sdkadapter.aso.xsd http://com.informatica.metadata.common.typesystem/2 com.informatica.metadata.common.typesystem.xsd http://com.informatica.adapter.sdkadapter.capabilityattribute/2 com.informatica.adapter.sdkadapter.capabilityattribute.xsd http://com.informatica.adapter.sdkadapter.projection.sinkoperation/2 com.informatica.adapter.sdkadapter.projection.sinkoperation.xsd">
"""

	aso_D_ASOOperation_id = uuid.uuid4()
	dataSource_id = uuid.uuid4()

	extStr = extStr + f"""<aso:D_ASOOperation imx:id="U:{aso_D_ASOOperation_id}" dataSource="U:{dataSource_id}" name="tableWrite" baseASO="U:{dataSource_id}" operationType="tableWrite" typeSystem="smd:com.infa.adapter.bigquery.typesystem.BigqueryTypeSystem.typesystem">
"""

	defaultConfig_id = uuid.uuid4()
	groupType_id = uuid.uuid4()

	extStr = extStr + f"""<operations>
<Capability imx:id="ID_1" xsi:type="datasourceoperation:WriteCapability" defaultAdapter="smd:com.informatica.adapter.seed.sdkadapter.CanonicalSDKAdapter.sdkDataAdapter" defaultConfig="U:{defaultConfig_id}">
<inGroups>
<DataAccessGroup imx:id="ID_2" xsi:type="datasourceoperation:DataAccessGroup" groupType="U:{groupType_id}"/>
</inGroups>
</Capability>
</operations>
"""

	###############################################################################
	# 							capabilityattribute
	###############################################################################
	projectionBindings_id = uuid.uuid4()

	extStr = extStr + f"""<ownedCapabilityTypes>
<ComplexType imx:id="U:{groupType_id}" xsi:type="capabilityattribute:D_ComplexType" projectionBindings="U:{projectionBindings_id}">
<features>
"""


	capability_ids = []
	for fld in tgtFields:
		capability_id = uuid.uuid4()			
		extStr = extStr + f"""<StructuralFeature imx:id="U:{capability_id}" xsi:type="capabilityattribute:D_StructuralFeature" type="smd:com.informatica.metadata.seed.platform.Platform.typesystem%2F{fld['SRC_DATA_TYPE']}" name="{fld['COLUMN_NAME']}" precision="{fld['PRECISION']}" scale="{fld['SCALE']}"/>
"""
		capability_ids.append(capability_id)
		
	extStr = extStr + """</features>
</ComplexType>
</ownedCapabilityTypes>
"""

	typeLibrary_id  = uuid.uuid4()
	extStr = extStr + f"""<typeLibrary imx:id="U:{typeLibrary_id}" xsi:type="typelibrary:TypeLibrary"/>
"""

	extStr = extStr + f"""<projections>
<D_Projection imx:id="U:{projectionBindings_id}" xsi:type="projection:D_Projection" outputProjection="true">
<operations>
"""

	###############################################################################
	# 							D_PlatformSource
	###############################################################################
	sourceoper_id = uuid.uuid4()

	extStr = extStr + f"""<D_OperationBase imx:id="U:{sourceoper_id}" xsi:type="sourceoperation:D_PlatformSource" name="PlatformSource" group="U:{groupType_id}">
<fields>
"""


	platformField_ids = []
	for r, fld in enumerate(tgtFields):
		platformField_id = uuid.uuid4()
			
		extStr = extStr + f"""<D_FieldBase imx:id="U:{platformField_id}" xsi:type="projection:D_PlatformField" name="{fld['COLUMN_NAME']}" precision="{fld['PRECISION']}" scale="{fld['SCALE']}" type="smd:com.informatica.metadata.seed.platform.Platform.typesystem%2F{fld['SRC_DATA_TYPE']}" structuralFeature="U:{capability_ids[r]}"/>
"""
		platformField_ids.append(platformField_id)

	extStr = extStr + """</fields>
</D_OperationBase>
"""

	###############################################################################
	# 							D_ConversionOperation
	###############################################################################
	conversionoper_id = uuid.uuid4()

	extStr = extStr + f"""<D_OperationBase imx:id="U:{conversionoper_id}" xsi:type="conversionoperation:D_ConversionOperation" name="TypeConvert" inputOperation="U:{sourceoper_id}">
<fields>
"""

	for r, fld in enumerate(tgtFields):
		derivedField_id = uuid.uuid4()			
		extStr = extStr + f"""<D_FieldBase imx:id="U:{derivedField_id}" xsi:type="projection:D_DerivedField" ancestorField="U:{platformField_ids[r]}" name="{fld['COLUMN_NAME']}" precision="{fld['PRECISION']}" scale="{fld['SCALE']}" type="smd:com.infa.adapter.bigquery.typesystem.BigqueryTypeSystem.typesystem%2F{fld['DATA_TYPE']}"/>
"""

	extStr = extStr + """</fields>
</D_OperationBase>
"""

	sinkoper_id = uuid.uuid4()
	sinkoper_node_id = uuid.uuid4()

	extStr = extStr + f"""<D_OperationBase imx:id="U:{sinkoper_id}" xsi:type="sinkoperation:D_NativeSink" name="NativeSink" inputOperation="U:{conversionoper_id}" node="U:{sinkoper_node_id}"/>
"""

	extStr = extStr + """</operations>
</D_Projection>
</projections>
"""

	extStr = extStr + """<writeCapAttributes>
<D_WriteCapabilityAttributes imx:id="ID_3" xsi:type="capabilityattribute:D_WriteCapabilityAttributes">
<modelExtension imx:id="ID_4" xsi:type="capability:TableWriteCapabilityAttributesExtension"/>
</D_WriteCapabilityAttributes>
</writeCapAttributes>
"""

	extStr = extStr + """</aso:D_ASOOperation>
"""


	lGraph_id = uuid.uuid4()
	connectInfo_id = uuid.uuid4()
	rootNode_id = uuid.uuid4()
	containerRelationship_id = uuid.uuid4()

	extStr = extStr + f"""<aso1:ComplexASO imx:id="U:{dataSource_id}" name="dummyaso" createdBy="user" extensionId="com.infa.adapter.bigquery" lGraphs="U:{lGraph_id}" nmoType="table" patternName="bigquerybigquery_table_Pattern">
"""
	extStr = extStr + f"""<asoOperations>
<D_ASOOperation imx:idref="U:{aso_D_ASOOperation_id}" xsi:type="aso:D_ASOOperation"/>
</asoOperations>
"""
	extStr = extStr + f"""<defaultRuntimeConfig imx:id="U:{defaultConfig_id}" xsi:type="asoconfig:D_ASORuntimeConfig" connectInfo="U:{connectInfo_id}"/>
<lGraph imx:id="U:{lGraph_id}" xsi:type="catalog:P_Catalog" extensionId="com.infa.adapter.bigquery" nmoType="table" patternName="bigquerybigquery_table_Pattern" rootNodes="U:{rootNode_id}">
"""
	extStr = extStr + f"""<arcs>
<L_Arc imx:id="U:{containerRelationship_id}" xsi:type="container:P_ContainerRelationship" child="U:{sinkoper_node_id}" name="{dsNm}-%3E{tabNm}" parent="U:{rootNode_id}"/>
</arcs>
"""


	###############################################################################
	# 							P_Field
	###############################################################################
	extStr = extStr + f"""<nodes>
<L_Node imx:id="U:{sinkoper_node_id}" xsi:type="flatrecord:P_FlatRecord" nativeName="{tabNm}" name="{tabNm}" nmoType="table">
<extensions imx:id="ID_5" xsi:type="metadata:TableRecordExtensions" connectorType="Simple" recordType="TABLE"/>
<fields>
"""

	for r, fld in enumerate(tgtFields):
		field_id = uuid.uuid4()
		extStr = extStr + f"""<L_FieldBase imx:id="U:{field_id}" xsi:type="field:P_Field" name="{fld['COLUMN_NAME']}" nativeName="{fld['COLUMN_NAME']}" type="smd:com.infa.adapter.bigquery.typesystem.BigqueryTypeSystem.typesystem%2F{fld['DATA_TYPE']}" length="{fld['PRECISION']}" nullableField="true" precision="{fld['PRECISION']}" scale="{fld['SCALE']}">
"""
		
		extStr = extStr + f"""<extensions imx:id="ID_{r+6}" xsi:type="metadata:TableFieldExtensions"/>
</L_FieldBase>
"""

	extStr = extStr + f"""</fields>
</L_Node>
<L_Node imx:id="U:{rootNode_id}" xsi:type="container:P_Package" name="{dsNm}" nativeName="{dsNm}"/>
</nodes>
"""

	extStr = extStr + """</lGraph>
</aso1:ComplexASO>
"""
		
		
	###############################################################################
	# 							BigQueryConnectInfo
	###############################################################################
	extStr = extStr + f"""<connection:BigQueryConnectInfo imx:id="U:{connectInfo_id}" connectionType="com.infa.adapter.bigquery.connection.BigQueryConnectInfo">
<sdkConnectInfoModelExtension imx:id="ID_999" xsi:type="connection:BigQueryConnectInfoExtension" clientEmail="{os.getenv('BQ_CLIENT_EMAIL', '')}" privateKey="" projectId="{os.getenv('BQ_PROJECT_ID', '')}"/>
</connection:BigQueryConnectInfo>
</imx:IMX>"""

	return extStr

###############################################################################
###############################################################################
# 				TargetXML FUNCTION
###############################################################################
###############################################################################    	
def genBqTargetXmlStr(tgtNm, dsnm, tgtTbnm, dbms, instDivCd, rsltCol):

	tgtFields = []
	
	### Default Field
	# P_PTT
	tgtFldAttr = {'COLUMN_NAME':'P_PTT', 'DATA_TYPE':'DATE', 'SRC_DATA_TYPE':'date%2Ftime', 'PRECISION':29, 'SCALE':9}
	tgtFields.append(tgtFldAttr)
	# ETL_LOAD_TS
	tgtFldAttr = {'COLUMN_NAME':'ETL_LOAD_TS', 'DATA_TYPE':'TIMESTAMP', 'SRC_DATA_TYPE':'date%2Ftime', 'PRECISION':29, 'SCALE':9}
	tgtFields.append(tgtFldAttr)
	
	if instDivCd != None and instDivCd != '': #INSTANCE �ʵ� �߰�
		tgtFldAttr = {'COLUMN_NAME':'INSTANCE', 'DATA_TYPE':'STRING', 'SRC_DATA_TYPE':'string', 'PRECISION':50, 'SCALE':0}
		tgtFields.append(tgtFldAttr)
		
	for r, row in enumerate(rsltCol):
		v_column_name = row['column_name']
		v_data_type = row['data_type']
		v_data_length = row['data_length']
		v_data_precis = row['data_precision']
		v_data_scale = row['data_scale']
		v_nullable = row['null_yn']
		
		# data type
		if v_data_type.upper() in ('VARCHAR2', 'VARCHAR', 'NVARCHAR', 'NVARCHAR2', 'CHAR', 'CLOB', 'ROWID','TEXT','MEDIUMTEXT','CHARACTER VARYING'): #20240319 HARACTER VARYING 추가 이은송
			s_data_type = 'STRING'
		elif v_data_type.upper() == 'DATE':
			if dbms == 'ORACLE':    # Oracle -> ORACLE 수정(20111111 한병학)
				s_data_type = 'DATETIME'
			elif dbms in ('MySql','Microsoft SQL Server','MARIADB','POSTGRESQL'):  #20220110 MARIADB 추가 한병학
				s_data_type = 'DATE'
		elif v_data_type.upper() in ('DATETIME','DATETIME2','SMALLDATETIME'):  #20240621 SMALLDATETIME 추가 이은송
			s_data_type = 'DATETIME'
		elif v_data_type.upper() in ('TIMESTAMP', 'TIMESTAMP(6)','TIMESTAMP WITHOUT TIME ZONE'):
			s_data_type = 'TIMESTAMP'
		elif v_data_type.upper() in ('NUMBER', 'DECIMAL','NUMERIC','DOUBLE','MONEY','DOUBLE PRECISION'): # DOUBLE PRECISION 추가 20240409 jsoh / MONEY타입(MS-SQL) 추가 (이은송, 23/10/27)
			if v_data_precis > 0 and v_data_scale == 0:
				s_data_type = 'INTEGER'
			else:
				s_data_type = 'NUMERIC'
		elif v_data_type.upper() == 'FLOAT':
			s_data_type = 'NUMERIC'
		elif v_data_type.upper() in ('INT','TINYINT','BIGINT','SMALLINT','INTEGER'):
			s_data_type = 'INTEGER'
		elif v_data_type.upper() in ('BLOB','MEDIUMBLOB'):
			s_data_type = 'BYTES'
		elif v_data_type.upper() == 'RAW':
			s_data_type = 'BYTES'
		elif v_data_type.upper() == 'BOOLEAN':
			if dbms == 'POSTGRESQL':
				s_data_type = 'STRING'
			else:
				s_data_type = 'BOOLEAN'

		# precision	/ scale
		if s_data_type == 'STRING':
			s_src_data_type = 'string'
			s_precision = 80000
			s_scale = 0
		if s_data_type == 'BYTES':
			s_src_data_type = 'binary'
			s_precision = 80000
			s_scale = 0
		elif s_data_type == 'NUMERIC':
			s_src_data_type = 'decimal'
			s_precision = 28
			s_scale = 9
		elif s_data_type in ('DATE', 'TIMESTAMP', 'DATETIME','SMALLDATETIME','DATETIME2'):
			s_src_data_type = 'date%2Ftime'
			s_precision = 29
			s_scale = 9
		elif s_data_type == 'INTEGER':
			s_src_data_type = 'bigint'
			s_precision = 19
			s_scale = 0
		elif s_data_type == 'BOOLEAN':
			s_src_data_type = 'text'
			s_precision = 8000
			s_scale = 0

		# 컬럼 타입 확인
		# print(f"COLUMN_NAME : {v_column_name}, v_data_type : {v_data_type}, s_data_type : {s_data_type}, s_src_data_type : {s_src_data_type}")
			
		tgtFldAttr = {'COLUMN_NAME':v_column_name, 'DATA_TYPE':s_data_type, 'SRC_DATA_TYPE':s_src_data_type, 'PRECISION':s_precision, 'SCALE':s_scale}
		tgtFields.append(tgtFldAttr)
		  
	tgtStr = f"""    <TARGET BUSINESSNAME ="" COMPONENTVERSION ="1000000" CONSTRAINT ="" DATABASETYPE ="bigquery" DESCRIPTION ="" NAME ="{tgtNm}" OBJECTVERSION ="1" TABLEOPTIONS ="" VERSIONNUMBER ="1">
"""

	for fld in tgtFields:
		tgtStr = tgtStr + f"""        <TARGETFIELD BUSINESSNAME ="" DATATYPE ="{fld['DATA_TYPE']}" DESCRIPTION ="" FIELDNUMBER ="1" KEYTYPE ="NOT A KEY" NAME ="{fld['COLUMN_NAME']}" NULLABLE ="NULL" PICTURETEXT ="" PRECISION ="{fld['PRECISION']}" SCALE ="{fld['SCALE']}">
	          <FIELDATTRIBUTE NAME ="isRepeatable" VALUE =""/>
	          <FIELDATTRIBUTE NAME ="isRecord" VALUE =""/>
	       </TARGETFIELD>
"""

	extensionStr = genExtensionStr(dsnm, tgtTbnm, tgtFields)
	escape_table = {
		'"': "&quot;",
		"'": "&apos;"
	}
	escapeStr = escape(extensionStr, escape_table)
	#print(escapeStr)

	tgtStr = tgtStr + f"""        <METADATAEXTENSION COMPONENTVERSION ="1000000" DATATYPE ="STRING" DESCRIPTION ="" DOMAINNAME ="bigquery DOMAIN" ISCLIENTEDITABLE ="NO" ISCLIENTVISIBLE ="YES" ISREUSABLE ="YES" ISSHAREREAD ="YES" ISSHAREWRITE ="NO" MAXLENGTH ="2000000" NAME ="WriteOperation" VALUE ="{escapeStr}" VENDORNAME ="INFORMATICA"/>
	    </TARGET>
"""

	return tgtStr    
    
    
