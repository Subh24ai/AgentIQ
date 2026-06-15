import type { JSX } from 'react'

/** AgentIQ logo mark — a gradient tile with an abstract agent-network glyph. */
export default function Logo({ size = 30 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect width="32" height="32" rx="9" fill="url(#aiq-grad)" />
      <g stroke="#1a1205" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.5 11.5 L16 21 L21.5 11.5" />
      </g>
      <circle cx="10.5" cy="11" r="2.6" fill="#1a1205" />
      <circle cx="21.5" cy="11" r="2.6" fill="#1a1205" />
      <circle cx="16" cy="21" r="2.6" fill="#1a1205" />
      <defs>
        <linearGradient id="aiq-grad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffd479" />
          <stop offset="1" stopColor="#f0a500" />
        </linearGradient>
      </defs>
    </svg>
  )
}
