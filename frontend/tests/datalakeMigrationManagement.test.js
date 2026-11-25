import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildMigrationManagementRows,
  getMigrationStatusTargets,
  migrationIdentityKey,
} from '../src/datalakeMigrationManagement.js'

const table = (overrides = {}) => ({
  system_cd: 'SYS',
  instance_name: 'SOURCE',
  postfix: '',
  owner: 'OWNER',
  table_name: 'CUSTOMER',
  ...overrides,
})

test('status checks are requested only for tables with both physical targets', () => {
  const tables = [table(), table({ table_name: 'ST_ONLY' }), table({ table_name: 'NO_ST' })]
  const physicalStatuses = {
    [migrationIdentityKey(tables[0])]: { st_table_exists: true, table_exists: true },
    [migrationIdentityKey(tables[1])]: { st_table_exists: true, table_exists: false },
    [migrationIdentityKey(tables[2])]: { st_table_exists: false, table_exists: false },
  }

  assert.deepEqual(getMigrationStatusTargets(tables, physicalStatuses), [tables[0]])
})

test('management rows combine physical and migration state without losing table identity', () => {
  const registered = [table(), table({ table_name: 'NEW_TABLE' })]
  const statuses = {
    [migrationIdentityKey(registered[0])]: { st_table_exists: true, table_exists: true },
    [migrationIdentityKey(registered[1])]: { st_table_exists: false, table_exists: false },
  }
  const migrations = {
    [migrationIdentityKey(registered[0])]: { needs_migration: true, status: 'READY', route: 'APPLY_EMPTY', reason: '빈 테이블 변경 가능' },
  }

  assert.deepEqual(buildMigrationManagementRows(registered, statuses, migrations), [
    { table: registered[0], key: migrationIdentityKey(registered[0]), physical: statuses[migrationIdentityKey(registered[0])], migration: migrations[migrationIdentityKey(registered[0])], state: 'NEEDS_MIGRATION' },
    { table: registered[1], key: migrationIdentityKey(registered[1]), physical: statuses[migrationIdentityKey(registered[1])], migration: null, state: 'CREATE_REQUIRED' },
  ])
})

test('unknown physical inspection is not mislabeled as a missing table', () => {
  const registered = [table()]
  const key = migrationIdentityKey(registered[0])
  const rows = buildMigrationManagementRows(registered, { [key]: { status: 'UNKNOWN' } }, {})

  assert.equal(rows[0].state, 'CHECK_FAILED')
})

test('migration identity keeps system, source, postfix, owner, and table distinct', () => {
  assert.notEqual(migrationIdentityKey(table()), migrationIdentityKey(table({ postfix: 'X' })))
  assert.notEqual(migrationIdentityKey(table()), migrationIdentityKey(table({ owner: 'OTHER' })))
})
