import type { JSX } from 'react'
import type { StepStatus } from '../types'

interface Props {
  label: string
  status: StepStatus
  index: number
  isLast?: boolean
}

export default function AgentStep({ label, status, index, isLast }: Props): JSX.Element {
  return (
    <div className="step-wrap">
      <div className={`step step-${status}`}>
        <span className="step-dot">{status === 'complete' ? '✓' : index + 1}</span>
        <span className="step-label">{label}</span>
      </div>
      {!isLast && <div className={`step-connector ${status === 'complete' ? 'done' : ''}`} />}
    </div>
  )
}
