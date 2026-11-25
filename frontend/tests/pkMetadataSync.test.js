import assert from 'node:assert/strict'
import test from 'node:test'
import { syncRegisteredPkColumns } from '../src/pkMetadataSync.js'

test('source PK synchronization updates the visible registered columns using source-name casing', () => {
  const selected = {
    table_name: 'ORDERS',
    columns: [
      { column_name: 'ID', column_id: 1, pk_yn: 'N', comment: 'identifier' },
      { column_name: 'NAME', column_id: 2, pk_yn: 'N' },
    ],
  }

  const synced = syncRegisteredPkColumns(selected, ['id'])

  assert.deepEqual(synced.columns.map(({ column_name, pk_yn }) => [column_name, pk_yn]), [
    ['ID', 'Y'],
    ['NAME', 'N'],
  ])
  assert.equal(synced.columns[0].comment, 'identifier')
  assert.equal(selected.columns[0].pk_yn, 'N', 'update must not mutate the stale original object')
})

test('empty source PK list clears prior PK flags in the registered detail model', () => {
  const selected = { columns: [{ column_name: 'ID', pk_yn: 'Y' }, { column_name: 'NAME', pk_yn: 'N' }] }
  const synced = syncRegisteredPkColumns(selected, [])
  assert.deepEqual(synced.columns.map(column => column.pk_yn), ['N', 'N'])
})
