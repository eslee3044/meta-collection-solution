-- Run as the dedicated Oracle test user.
whenever sqlerror exit sql.sqlcode

begin
  execute immediate 'drop view MV_TEST_ORDER_SUMMARY';
exception when others then
  if sqlcode != -942 then raise; end if;
end;
/

begin
  execute immediate 'drop table MV_TEST_ORDERS cascade constraints purge';
exception when others then
  if sqlcode != -942 then raise; end if;
end;
/

begin
  execute immediate 'drop table MV_TEST_CUSTOMERS cascade constraints purge';
exception when others then
  if sqlcode != -942 then raise; end if;
end;
/
