import { useEffect, useRef } from 'react'
import type { JSX } from 'react'
import type { AgentEvent } from '../types'

function fmtTime(iso: string): string {
  const d = iso ? new Date(iso) : new Date()
  return d.toLocaleTimeString('en-GB', { hour12: false })
}

function summarize(event: AgentEvent): string {
  const out = event.partial_output || {}
  // Show the most meaningful field available for this node.
  const candidate =
    (out.company_summary as string) ??
    (out.fit_reasoning as string) ??
    (out.subject as string) ??
    (out.feedback as string)
  if (candidate) return String(candidate)
  return event.status === 'active' ? 'working…' : 'done'
}

export default function EventFeed({ events }: { events: AgentEvent[] }): JSX.Element {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="event-feed">
      {events.length === 0 ? (
        <div className="feed-empty">Waiting for the pipeline to start…</div>
      ) : (
        events.map((e, i) => (
          <div key={i} className={`feed-line feed-${e.status}`}>
            <span className="feed-time">[{fmtTime(e.timestamp)}]</span>{' '}
            <span className="feed-node">{e.node.toUpperCase()}</span>:{' '}
            <span className="feed-text">{summarize(e)}</span>
          </div>
        ))
      )}
      <div ref={endRef} />
    </div>
  )
}
