import { useEffect, useRef } from 'react'
import type { JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { streamRun } from '../api'
import { clearToken, getToken } from '../auth'
import { useStore } from '../store'
import { PIPELINE_NODES } from '../types'
import type { AgentEvent, StepStatus } from '../types'
import AgentStep from '../components/AgentStep'
import EventFeed from '../components/EventFeed'
import CostBadge from '../components/CostBadge'
import HITLPanel from '../components/HITLPanel'

const NODE_LABELS: Record<string, string> = {
  researcher: 'Researcher',
  analyst: 'Analyst',
  drafter: 'Drafter',
  evaluator: 'Evaluator',
}

function stepStatus(node: string, events: AgentEvent[]): StepStatus {
  const ofNode = events.filter((e) => e.node === node)
  if (ofNode.some((e) => e.status === 'complete')) return 'complete'
  if (ofNode.some((e) => e.status === 'active')) return 'active'
  return 'pending'
}

export default function RunPage(): JSX.Element {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const esRef = useRef<EventSource | null>(null)

  const { agentEvents, hitlPayload, finalState, tokenUsage } = useStore()
  const { resetStore, setRunId, appendEvent, setHITL, setFinal } = useStore()

  const token = getToken()

  useEffect(() => {
    if (!token) {
      navigate('/')
      return
    }
    resetStore()
    setRunId(runId)
    const es = streamRun(runId, token, appendEvent, setHITL, setFinal)
    esRef.current = es
    return () => {
      es.close()
      esRef.current = null
    }
    // Re-open only when the run id changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  function onHITLResolved(): void {
    // Clear the panel and keep listening — the backend publishes the post-resume
    // events (and ultimately the complete event) on the same stream.
    setHITL(null)
  }

  const draft = finalState?.draft_output
  const evalOut = finalState?.eval_output
  const analysis = finalState?.analysis_output

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          Agent<span className="brand-accent">IQ</span>
        </div>
        <div className="topbar-right">
          <CostBadge usage={tokenUsage} />
          <button
            className="btn btn-ghost"
            onClick={() => {
              clearToken()
              navigate('/')
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="content run-layout">
        <section className="run-main">
          <h1>Run {runId.slice(0, 8)}…</h1>

          <div className="pipeline">
            {PIPELINE_NODES.map((node, i) => (
              <AgentStep
                key={node}
                label={NODE_LABELS[node]}
                status={stepStatus(node, agentEvents)}
                isLast={i === PIPELINE_NODES.length - 1}
              />
            ))}
          </div>

          <h2 className="section-title">Live output</h2>
          <EventFeed events={agentEvents} />

          {finalState && (
            <div className="card summary">
              <h2>Run complete</h2>
              {finalState.error ? (
                <div className="error-text">Pipeline error: {finalState.error}</div>
              ) : (
                <div className="summary-grid">
                  <div>
                    <span className="summary-label">Fit score</span>
                    <span className="summary-value">
                      {analysis?.fit_score != null ? analysis.fit_score.toFixed(2) : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="summary-label">Eval score</span>
                    <span className="summary-value">
                      {evalOut?.score != null ? evalOut.score.toFixed(2) : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="summary-label">Draft subject</span>
                    <span className="summary-value">{draft?.subject ?? '—'}</span>
                  </div>
                  <div>
                    <span className="summary-label">Passed eval</span>
                    <span className="summary-value">{evalOut?.passed ? 'Yes' : 'No'}</span>
                  </div>
                  <div>
                    <span className="summary-label">Total cost</span>
                    <span className="summary-value">~${tokenUsage.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {hitlPayload && token && (
          <HITLPanel
            payload={hitlPayload}
            runId={runId}
            token={token}
            onResolved={onHITLResolved}
          />
        )}
      </main>
    </div>
  )
}
