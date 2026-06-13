import type { JSX } from 'react'
import type { TokenUsage } from '../types'

export default function CostBadge({ usage }: { usage: TokenUsage }): JSX.Element {
  return (
    <div className="cost-badge" title="Live token usage and estimated cost">
      <span className="cost-up">↑ {usage.prompt_tokens}</span>
      <span className="cost-down">↓ {usage.completion_tokens}</span>
      <span className="cost-usd">~${usage.cost_usd.toFixed(4)}</span>
    </div>
  )
}
