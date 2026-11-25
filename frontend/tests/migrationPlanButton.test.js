import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { isMigrationRequestCurrent, shouldShowMigrationButton } from '../src/migrationStatusRequest.js'
import { MigrationPlanButton } from '../src/MigrationPlanButton.js'

test('migration plan button is shown only for confirmed changes on a clean idle selection', () => {
  assert.equal(shouldShowMigrationButton(true, false, false), true)
  assert.equal(shouldShowMigrationButton(false, false, false), false)
  assert.equal(shouldShowMigrationButton(undefined, false, false), false)
  assert.equal(shouldShowMigrationButton(true, true, false), false)
  assert.equal(shouldShowMigrationButton(true, false, true), false)
})

test('stale status results are rejected after selection, metadata, or request changes', () => {
  const selectedA = { table_name: 'A' }
  const originalA = { table_name: 'A' }
  assert.equal(isMigrationRequestCurrent(4, 4, selectedA, selectedA, originalA, originalA), true)
  assert.equal(isMigrationRequestCurrent(4, 5, selectedA, selectedA, originalA, originalA), false)
  assert.equal(isMigrationRequestCurrent(4, 4, selectedA, { table_name: 'B' }, originalA, originalA), false)
  assert.equal(isMigrationRequestCurrent(4, 4, selectedA, selectedA, originalA, { table_name: 'A' }), false)
})

test('migration plan button does not render before a positive status check', () => {
  const html = renderToStaticMarkup(React.createElement(MigrationPlanButton, {
    visible: false,
    busy: false,
    disabled: false,
    onClick: () => {},
  }))
  assert.equal(html, '')
})

test('visible migration plan button uses the warning action class and busy label', () => {
  const html = renderToStaticMarkup(React.createElement(MigrationPlanButton, {
    visible: true,
    busy: true,
    disabled: true,
    title: '구조 변경 계획 안내',
    onClick: () => {},
  }))
  assert.match(html, /class="ghost datalake-migration-trigger"/)
  assert.match(html, /disabled=""/)
  assert.match(html, /구조 비교 중…/)
})
