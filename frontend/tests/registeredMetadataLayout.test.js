import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/registered-metadata.css', import.meta.url), 'utf8')
const sharedStyles = readFileSync(new URL('../src/admin-metadata.css', import.meta.url), 'utf8')
const cssRules = [...styles.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectorText, body]) => {
  const declarations = Object.fromEntries(body.split(';').flatMap(declaration => {
    const separator = declaration.indexOf(':')
    return separator < 0 ? [] : [[declaration.slice(0, separator).trim(), declaration.slice(separator + 1).trim()]]
  }))
  return { selectors: selectorText.split(',').map(selector => selector.trim()), declarations }
})
const hasCssRule = (selector, expected) => cssRules.some(rule =>
  rule.selectors.includes(selector) && Object.entries(expected).every(([property, value]) => rule.declarations[property] === value)
)

test('collapsed basic-info panel uses a state class that cannot trigger the global icon rotation', () => {
  const section = component.match(/className=\{`form-section registered-basic-section\$\{basicInfoOpen \? '[^']+' : '[^']+'\}`\}/)?.[0] || ''

  assert.match(sharedStyles, /\.collapsed\s*\{\s*transform:\s*rotate\(-90deg\)\s*\}/)
  assert.match(section, /basicInfoOpen \? ' is-expanded' : ' is-collapsed'/)
  assert.doesNotMatch(section, /' collapsed'/)
  assert.match(styles, /\.form-section\.registered-basic-section\.is-collapsed \.registration-section-head/)
  assert.match(styles, /\.form-section\.registered-basic-section\.is-expanded\{padding:14px 16px 16px\}/)
})

test('registered table basic information follows PK settings and uses the table-specific heading', () => {
  const start = component.indexOf('function RegisteredMetadataPage')
  const end = component.indexOf('\nfunction ', start + 10)
  const page = component.slice(start, end < 0 ? component.length : end)

  assert.ok(page.indexOf('<PkSettingsCard') < page.indexOf('registered-basic-section'))
  assert.match(page, /<b>테이블 기본 정보<\/b>/)
})

test('metadata table registration modal uses the table-specific basic-information heading', () => {
  assert.equal(component.split('<b>테이블 기본 정보</b>').length - 1, 2)
})

test('PK settings card and source-PK controls use compact desktop dimensions', () => {
  assert.ok(hasCssRule('.pk-settings-card', { display: 'grid', gap: '8px', margin: '12px 16px', padding: '10px 14px' }))
  assert.ok(hasCssRule('.pk-settings-head h4', { 'font-size': '14px' }))
  assert.ok(hasCssRule('.pk-source-lock', { padding: '8px 10px' }))
  assert.ok(hasCssRule('.pk-settings-card .pk-source-lock-head button', { 'min-height': '32px', padding: '6px 10px', 'font-size': '11px' }))
  assert.ok(hasCssRule('.pk-settings-card .pk-settings-head .icon-btn', { width: '32px', height: '32px' }))
  assert.ok(hasCssRule('.pk-candidate-card', { gap: '7px', padding: '12px' }))
  assert.ok(hasCssRule('.pk-validation', { gap: '3px', padding: '8px 10px', 'font-size': '9px' }))
  assert.match(component, /sourceLocked && <div className="pk-source-lock">/)
})

test('PK settings controls remain compact and stacked on mobile', () => {
  assert.ok(hasCssRule('.pk-settings-card', { margin: '10px', padding: '10px' }))
  assert.ok(hasCssRule('.pk-source-lock-head', { 'align-items': 'stretch', 'flex-direction': 'column' }))
  assert.ok(hasCssRule('.pk-source-lock-head button', { width: '100%' }))
  assert.ok(hasCssRule('.pk-toolbar button', { width: '100%' }))
})
