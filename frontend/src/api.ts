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
 * Open an SSE stream for a run using fetch() + ReadableStream so the JWT can be
 * sent in the Authorization header (EventSource cannot set headers). Each SSE
 * message's `data:` line is a JSON object of the form {event, data}.
 * Returns a cleanup function that aborts the stream.
 */
export function streamRun(
  runId: string,
  token: string,
  onEvent: (e: AgentEvent) => void,
  onHITL: (p: HITLPayload) => void,
  onComplete: (s: CompletePayload['final_state']) => void,
  onError?: (err: Error) => void,
): () => void {
  const controller = new AbortController()

  ;(async () => {
    try {
      const res = await fetch(`${API}/runs/${runId}/stream`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`Stream ${res.status}`)
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? '' // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const parsed = JSON.parse(line.slice(6))
            if (parsed.event === 'update') onEvent(parsed.data)
            else if (parsed.event === 'hitl_required') onHITL(parsed.data)
            else if (parsed.event === 'complete') {
              onComplete(parsed.data.final_state)
              return
            }
          } catch {
            /* malformed line — skip */
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onError?.(err as Error)
      }
    }
  })()

  return () => controller.abort() // cleanup function
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
