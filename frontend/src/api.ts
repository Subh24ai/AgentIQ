import type {
  AgentEvent,
  CompletePayload,
  HITLPayload,
  Lead,
  RunRecord,
} from './types'

const API = '/api'

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return res.json() as Promise<T>
}

/** Exchange username/password for a JWT (OAuth2 password form). */
export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch(`${API}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  const data = await asJson<{ access_token: string }>(res)
  return data.access_token
}

export async function createRun(lead: Lead, token: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API}/runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(lead),
  })
  return asJson<{ run_id: string }>(res)
}

/**
 * Open an SSE stream for a run. EventSource cannot set headers, so the JWT is
 * passed as a query param (the backend stream endpoint accepts ?token=).
 * Returns the EventSource so the caller can close() it.
 */
export function streamRun(
  runId: string,
  token: string,
  onEvent: (e: AgentEvent) => void,
  onHITL: (p: HITLPayload) => void,
  onComplete: (p: CompletePayload) => void,
): EventSource {
  const es = new EventSource(`${API}/runs/${runId}/stream?token=${encodeURIComponent(token)}`)

  es.addEventListener('update', (ev) => onEvent(JSON.parse((ev as MessageEvent).data)))
  es.addEventListener('hitl_required', (ev) => onHITL(JSON.parse((ev as MessageEvent).data)))
  es.addEventListener('complete', (ev) => {
    onComplete(JSON.parse((ev as MessageEvent).data))
    es.close()
  })

  return es
}

export async function submitHITL(
  runId: string,
  decision: 'approved' | 'rejected',
  feedback: string,
  token: string,
): Promise<{ status: string; decision: string }> {
  const res = await fetch(`${API}/runs/${runId}/hitl`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ decision, feedback }),
  })
  return asJson<{ status: string; decision: string }>(res)
}

export async function getRun(runId: string, token: string): Promise<RunRecord> {
  const res = await fetch(`${API}/runs/${runId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return asJson<RunRecord>(res)
}
