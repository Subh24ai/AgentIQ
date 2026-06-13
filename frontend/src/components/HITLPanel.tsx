import { useState } from 'react'
import type { JSX } from 'react'
import { submitHITL } from '../api'
import type { HITLPayload } from '../types'

interface Props {
  payload: HITLPayload
  runId: string
  token: string
  onResolved: (decision: 'approved' | 'rejected') => void
}

export default function HITLPanel({ payload, runId, token, onResolved }: Props): JSX.Element {
  const [body, setBody] = useState(payload.draft.body ?? '')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<string>('')

  async function decide(decision: 'approved' | 'rejected'): Promise<void> {
    if (decision === 'rejected' && notes.trim() === '') {
      setError('Reviewer notes are required when rejecting.')
      return
    }
    setError('')
    setBusy(true)
    try {
      const feedback = decision === 'rejected' ? notes : notes || 'Approved as drafted.'
      await submitHITL(runId, decision, feedback, token)
      setDone('Decision submitted')
      onResolved(decision)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit decision')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="hitl-panel" role="dialog" aria-label="Human review">
      <div className="hitl-head">
        <h2>Human review required</h2>
        <span className="badge badge-warn">Eval below threshold</span>
      </div>

      <div className="hitl-field">
        <span className="hitl-label">Subject</span>
        <div className="hitl-subject">{payload.draft.subject ?? '(no subject)'}</div>
      </div>

      <div className="hitl-field">
        <span className="hitl-label">Body (editable)</span>
        <textarea
          className="hitl-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={10}
        />
      </div>

      <div className="hitl-field">
        <span className="hitl-label">Evaluator feedback</span>
        <div className="hitl-feedback">{payload.eval_feedback || '(none)'}</div>
      </div>

      <div className="hitl-field">
        <span className="hitl-label">Reviewer notes (required to reject)</span>
        <textarea
          className="hitl-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Why are you approving / rejecting?"
        />
      </div>

      {error && <div className="error-text">{error}</div>}
      {done ? (
        <div className="hitl-done">{done}</div>
      ) : (
        <div className="hitl-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => decide('approved')}>
            Approve &amp; Send
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => decide('rejected')}>
            Reject with feedback
          </button>
        </div>
      )}
    </aside>
  )
}
