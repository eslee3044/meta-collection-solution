import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('../src/DatalakeSchemaMigrationManagement.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/datalake-migration-management.css', import.meta.url), 'utf8')

test('migration-needed badge and plan button share a responsive control row', () => {
  const controls = component.match(/<div className="dmm-row-controls">([\s\S]*?)<\/div>/)?.[1] || ''

  assert.match(controls, /dmm-status/)
  assert.match(controls, /dmm-plan-button/)
  assert.match(controls, /변경 계획 보기/)
  assert.match(styles, /\.dmm-row-controls\{[^}]*display:flex;[^}]*align-items:center;[^}]*justify-content:space-between/)
  assert.match(styles, /\.dmm-row-title\{[^}]*flex-direction:column/)
  assert.match(styles, /\.dmm-row-controls\{[^}]*width:100%/)
})
