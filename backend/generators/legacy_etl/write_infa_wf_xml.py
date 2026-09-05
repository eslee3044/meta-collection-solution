import sys
import os
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("-n", "--name", 	required=True,	help="Workflow name (ex) wf_ST_GSFS_초기적재")
ap.add_argument("-p", "--parallel", required=True, 	help="Workflow parallel count - 동시 작업 갯수")
ap.add_argument("-f", "--file", 	required=False,	default="N",	help="session 정보를 file에서 읽을 것인가 여부 Y/N")
args = vars(ap.parse_args())

wfnm			= args["name"]
parallel_cnt	= args["parallel"]
file_yn			= args["file"]

parallel_cnt = int(parallel_cnt)

if file_yn == "Y":	# wf.txt 파일에서 세션을 가져온다
	with open('wf.txt', 'r', encoding='utf-8') as rf:
		sess_arr=rf.read().splitlines()
	# 첫번째 줄 깨진문자 발생하므로 제거
	sess_arr.pop(0)
else:				# session 폴더에서 세션을 가져온다
	os.chdir('session')
	sess_arr = [fl[:-4] for fl in os.listdir(".") if os.path.isfile(fl) and fl[:-4] != 'tt' and fl != 'tt']
	os.chdir('..')
# print(sess_arr)	

header_text = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE POWERMART SYSTEM "powrmart.dtd">
<POWERMART CREATION_DATE="05/12/2020 16:26:04" REPOSITORY_VERSION="188.97">
<REPOSITORY NAME="REP_LAKE" VERSION="188" CODEPAGE="UTF-8" DATABASETYPE="Microsoft SQL Server">
<FOLDER NAME="xml_gen" GROUP="" OWNER="Administrator" SHARED="NOTSHARED" DESCRIPTION="" PERMISSIONS="rwx---r--" UUID="xx">
"""

footer_text = """</FOLDER>
</REPOSITORY>
</POWERMART>
"""

xml_file = f'wf/{wfnm}.xml'
f = open(xml_file, 'w', encoding='utf-8')

f.write(header_text)

f.write(f"""    <WORKFLOW DESCRIPTION ="" ISENABLED ="YES" ISRUNNABLESERVICE ="NO" ISSERVICE ="NO" ISVALID ="YES" NAME ="{wfnm}" REUSABLE_SCHEDULER ="NO" SCHEDULERNAME ="스케줄러" SERVERNAME ="INT_LAKE" SERVER_DOMAINNAME ="Domain_LAKE" SUSPEND_ON_ERROR ="NO" TASKS_MUST_RUN_ON_SERVER ="NO" VERSIONNUMBER ="1">
        <SCHEDULER DESCRIPTION ="" NAME ="스케줄러" REUSABLE ="NO" VERSIONNUMBER ="1">
            <SCHEDULEINFO SCHEDULETYPE ="ONDEMAND"/>
        </SCHEDULER>
        <TASK DESCRIPTION ="" NAME ="시작" REUSABLE ="NO" TYPE ="Start" VERSIONNUMBER ="1"/>
        <TASKINSTANCE DESCRIPTION ="" ISENABLED ="YES" NAME ="시작" REUSABLE ="NO" TASKNAME ="시작" TASKTYPE ="Start"/>
""")

for sess_nm in sess_arr:
	f.write(f'        <TASKINSTANCE DESCRIPTION ="" FAIL_PARENT_IF_INSTANCE_DID_NOT_RUN ="NO" FAIL_PARENT_IF_INSTANCE_FAILS ="YES" ISENABLED ="YES" NAME ="{sess_nm}" REUSABLE ="YES" TASKNAME ="{sess_nm}" TASKTYPE ="Session" TREAT_INPUTLINK_AS_AND ="YES"/>\n')

# wf link를 만들기 위해 2d로 변경	
d2sess = []
for i in range (parallel_cnt):
    d2sess.append([])
for i in range(len(sess_arr)):
    d2sess[i%parallel_cnt].append(sess_arr[i])
    
for ss in d2sess:
	for x in range(len(ss)):
		if x == 0:
			f.write(f'        <WORKFLOWLINK CONDITION ="" FROMTASK ="시작" TOTASK ="{ss[x]}"/>\n')
		else:
			f.write(f'        <WORKFLOWLINK CONDITION ="" FROMTASK ="{ss[x-1]}" TOTASK ="{ss[x]}"/>\n')
		
f.write(f"""    		<WORKFLOWVARIABLE DATATYPE ="date/time" DEFAULTVALUE ="" DESCRIPTION ="The time this task started" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.StartTime" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="date/time" DEFAULTVALUE ="" DESCRIPTION ="The time this task completed" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.EndTime" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Status of this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.Status" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Status of the previous task that is not disabled" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.PrevTaskStatus" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Error code for this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.ErrorCode" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="Error message for this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$시작.ErrorMsg" USERDEFINED ="NO"/>
""")

for sess_nm in sess_arr:
	f.write(f"""        <WORKFLOWVARIABLE DATATYPE ="date/time" DEFAULTVALUE ="" DESCRIPTION ="The time this task started" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.StartTime" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="date/time" DEFAULTVALUE ="" DESCRIPTION ="The time this task completed" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.EndTime" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Status of this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.Status" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Status of the previous task that is not disabled" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.PrevTaskStatus" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Error code for this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.ErrorCode" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="Error message for this task&apos;s execution" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.ErrorMsg" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="bigint" DEFAULTVALUE ="" DESCRIPTION ="Rows successfully read" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.SrcSuccessRows" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="bigint" DEFAULTVALUE ="" DESCRIPTION ="Rows failed to read" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.SrcFailedRows" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="bigint" DEFAULTVALUE ="" DESCRIPTION ="Rows successfully loaded" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.TgtSuccessRows" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="bigint" DEFAULTVALUE ="" DESCRIPTION ="Rows failed to load" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.TgtFailedRows" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="Total number of transformation errors" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.TotalTransErrors" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="integer" DEFAULTVALUE ="" DESCRIPTION ="First error code" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.FirstErrorCode" USERDEFINED ="NO"/>
        <WORKFLOWVARIABLE DATATYPE ="string" DEFAULTVALUE ="" DESCRIPTION ="First error message" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="${sess_nm}.FirstErrorMsg" USERDEFINED ="NO"/>
""")

f.write(f"""        <WORKFLOWVARIABLE DATATYPE ="nstring" DEFAULTVALUE ="" DESCRIPTION ="" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$$Merge_Name" USERDEFINED ="YES"/>
        <WORKFLOWVARIABLE DATATYPE ="nstring" DEFAULTVALUE ="" DESCRIPTION ="" ISNULL ="NO" ISPERSISTENT ="NO" NAME ="$$Day" USERDEFINED ="YES"/>        
        <ATTRIBUTE NAME ="Parameter Filename" VALUE ="/engn001/pwc/server/infa_shared/BWParam/parameter_st_initial_load.prm"/>
        <ATTRIBUTE NAME ="Write Backward Compatible Workflow Log File" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Workflow Log File Name" VALUE ="{wfnm}.log"/>
        <ATTRIBUTE NAME ="Workflow Log File Directory" VALUE ="$PMWorkflowLogDir&#x5c;"/>
        <ATTRIBUTE NAME ="Save Workflow log by" VALUE ="By runs"/>
        <ATTRIBUTE NAME ="Save workflow log for these runs" VALUE ="0"/>
        <ATTRIBUTE NAME ="Service Name" VALUE =""/>
        <ATTRIBUTE NAME ="Service Timeout" VALUE ="0"/>
        <ATTRIBUTE NAME ="Is Service Visible" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Is Service Protected" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Fail task after wait time" VALUE ="0"/>
        <ATTRIBUTE NAME ="Enable HA recovery" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Automatically recover terminated tasks" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Service Level Name" VALUE ="Default"/>
        <ATTRIBUTE NAME ="Allow concurrent run with unique run instance name" VALUE ="NO"/>
        <ATTRIBUTE NAME ="Allow concurrent run with same run instance name" VALUE ="YES"/>
        <ATTRIBUTE NAME ="Maximum number of concurrent runs" VALUE ="0"/>
        <ATTRIBUTE NAME ="Assigned Web Services Hubs" VALUE =""/>
        <ATTRIBUTE NAME ="Maximum number of concurrent runs per Hub" VALUE ="1000"/>
        <ATTRIBUTE NAME ="Expected Service Time" VALUE ="1"/>
    </WORKFLOW>
""")

f.write(footer_text)

# 작업완료 표시 - (이은송C, 2024.02.21)
print(f"{xml_file} 파일이 생성되었습니다.")
