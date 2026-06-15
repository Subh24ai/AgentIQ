import { useEffect, useRef, useState } from 'react'
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
import Logo from '../components/Logo'

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
  const cleanupRef = useRef<() => void>(() => {})

  const { agentEvents, hitlPayload, finalState, tokenUsage } = useStore()
  const { resetStore, setRunId, appendEvent, setHITL, setFinal } = useStore()

  const [runError, setRunError] = useState<string | null>(null)

  const token = getToken()

  useEffect(() => {
    if (!token) {
      navigate('/')
      return
    }
    resetStore()
    setRunError(null)
    setRunId(runId)
    cleanupRef.current = streamRun(
      runId,
      token,
      appendEvent,
      setHITL,
      (finalState) => setFinal({ run_id: runId, final_state: finalState }),
      setRunError,
    )
    return () => {
      cleanupRef.current()
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
  const sent = finalState?.send_result?.recipient ? finalState.send_result : null

  return (
    <div className="page">
      <header className="topbar">
        <div className="auth-lockup">
          <Logo size={26} />
          <span className="brand">
            Agent<span className="brand-accent">IQ</span>
          </span>
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
          <div className="page-head">
            <h1>Run {runId.slice(0, 8)}…</h1>
            <p className="page-lede">Live multi-agent pipeline — research, analysis, draft, and evaluation.</p>
          </div>

          {runError && (
            <div className="error-banner">
              <span aria-hidden>⚠</span>
              <span>Run failed: {runError}</span>
            </div>
          )}

          <div className="pipeline">
            {PIPELINE_NODES.map((node, i) => (
              <AgentStep
                key={node}
                label={NODE_LABELS[node]}
                status={stepStatus(node, agentEvents)}
                index={i}
                isLast={i === PIPELINE_NODES.length - 1}
              />
            ))}
          </div>

          <h2 className="section-title">
            <span className="live-dot" aria-hidden />Live output
          </h2>
          <EventFeed events={agentEvents} />

          {finalState && (
            <div className="card summary">
              <h2>
                <span aria-hidden>{finalState.error ? '⚠' : '✓'}</span>
                {finalState.error ? 'Run ended with an error' : 'Run complete'}
              </h2>
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
                    <span className="summary-label">Passed eval</span>
                    <span className={`pill ${evalOut?.passed ? 'pill-pass' : 'pill-fail'}`}>
                      {evalOut?.passed ? '✓ Passed' : '✕ Failed'}
                    </span>
                  </div>
                  <div>
                    <span className="summary-label">Total cost</span>
                    <span className="summary-value">~${tokenUsage.cost_usd.toFixed(4)}</span>
                  </div>
                  <div>
                    <span className="summary-label">Draft subject</span>
                    <span className="summary-value small">{draft?.subject ?? '—'}</span>
                  </div>
                  {sent && (
                    <div>
                      <span className="summary-label">Email sent</span>
                      <span className="summary-value small">
                        {sent.recipient}
                        {sent.sent_at ? ` · ${new Date(sent.sent_at).toLocaleString()}` : ''}
                      </span>
                    </div>
                  )}
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
