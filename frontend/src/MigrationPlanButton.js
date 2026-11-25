import React from 'react'
import { CircleAlert } from 'lucide-react'

export function MigrationPlanButton({ visible, busy, disabled, title, onClick }) {
  if (!visible) return null
  return React.createElement(
    'button',
    { type: 'button', className: 'ghost datalake-migration-trigger', onClick, disabled, title },
    busy
      ? '구조 비교 중…'
      : React.createElement(React.Fragment, null, React.createElement(CircleAlert, { size: 16 }), ' 구조 변경 계획'),
  )
}
