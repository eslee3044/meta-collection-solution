import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')

test('schema information uses the same Korean success label for readable tables and views', () => {
  assert.match(app, /table\.permissions\?\.select\?'조회 가능'/)
  assert.match(app, /view\.permissions\?\.select\?'조회 가능'/)
  assert.doesNotMatch(app, /view\.permissions\?\.select\?'SELECT 가능'/)
})
