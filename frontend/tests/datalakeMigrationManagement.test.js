import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildMigrationManagementRows,
  canCloseMigrationModalOnEscape,
  getMigrationNeededRows,
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

test('status checks include registered tables with partial or missing physical targets', () => {
  const tables = [table(), table({ table_name: 'ST_ONLY' }), table({ table_name: 'NO_ST' })]
  const physicalStatuses = {
    [migrationIdentityKey(tables[0])]: { st_table_exists: true, table_exists: true },
    [migrationIdentityKey(tables[1])]: { st_table_exists: true, table_exists: false },
    [migrationIdentityKey(tables[2])]: { st_table_exists: false, table_exists: false },
  }

  assert.deepEqual(getMigrationStatusTargets(tables, physicalStatuses), tables)
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

test('the management list contains only migration-needed tables and searches within that set', () => {
  const needsChange = { table: table({ table_name: 'Customer_Archive' }), state: 'NEEDS_MIGRATION' }
  const current = { table: table({ table_name: 'Customer_Current' }), state: 'CURRENT' }
  const blocked = { table: table({ table_name: 'Customer_Blocked' }), state: 'CHECK_FAILED' }
  const rows = [needsChange, current, blocked]

  assert.deepEqual(getMigrationNeededRows(rows), [needsChange, blocked])
  assert.deepEqual(getMigrationNeededRows(rows, 'archive'), [needsChange])
  assert.deepEqual(getMigrationNeededRows(rows, 'current'), [])
  assert.deepEqual(getMigrationNeededRows([{ ...needsChange, table: table({ postfix: 'P2026' }) }], 'p2026'), [{ ...needsChange, table: table({ postfix: 'P2026' }) }])
})

test('Escape closes a migration dialog only when it is idle and not awaiting confirmation', () => {
  assert.equal(canCloseMigrationModalOnEscape({ busy: false, confirming: false }), true)
  assert.equal(canCloseMigrationModalOnEscape({ busy: true, confirming: false }), false)
  assert.equal(canCloseMigrationModalOnEscape({ busy: false, confirming: true }), false)
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
