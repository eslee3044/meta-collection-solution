import sys

filename = sys.argv[1]  # session/s_m_XXGIFH_GLOBAL_EMPLOYEE_T.xml

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

with open(filename,'r', encoding='utf-8') as contents:
      save = contents.read()
with open(filename,'w', encoding='utf-8') as contents:
      contents.write(header_text)
with open(filename,'a', encoding='utf-8') as contents:
      contents.write(save)
      contents.write(footer_text)