import type { MouseEventHandler, ReactElement } from 'react'
export function MigrationPlanButton(props: {
  visible: boolean
  busy: boolean
  disabled: boolean
  title?: string
  onClick: MouseEventHandler<HTMLButtonElement>
}): ReactElement | null
