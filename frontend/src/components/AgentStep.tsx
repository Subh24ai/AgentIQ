import type { JSX } from 'react'
import type { StepStatus } from '../types'

interface Props {
  label: string
  status: StepStatus
  isLast?: boolean
}

export default function AgentStep({ label, status, isLast }: Props): JSX.Element {
  return (
    <div className="step-wrap">
      <div className={`step step-${status}`}>
        <span className="step-dot">
          {status === 'complete' ? '✓' : status === 'active' ? '' : ''}
        </span>
        <span className="step-label">{label}</span>
      </div>
      {!isLast && <div className={`step-connector ${status === 'complete' ? 'done' : ''}`} />}
    </div>
  )
}
