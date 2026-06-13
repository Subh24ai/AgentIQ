import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { createRun } from '../api'
import { clearToken, getToken } from '../auth'
import type { Lead } from '../types'

const EMPTY: Lead = { company_name: '', website: '', icp_notes: '', recipient_email: '' }

export default function DashboardPage(): JSX.Element {
  const navigate = useNavigate()
  const [lead, setLead] = useState<Lead>(EMPTY)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function update<K extends keyof Lead>(key: K, value: Lead[K]): void {
    setLead((prev) => ({ ...prev, [key]: value }))
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const token = getToken()
      if (!token) {
        navigate('/')
        return
      }
      const { run_id } = await createRun(lead, token)
      navigate(`/run/${run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start run')
    } finally {
      setBusy(false)
    }
  }

  function logout(): void {
    clearToken()
    navigate('/')
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          Agent<span className="brand-accent">IQ</span>
        </div>
        <button className="btn btn-ghost" onClick={logout}>
          Sign out
        </button>
      </header>

      <main className="content narrow">
        <h1>New outreach run</h1>
        <p className="muted">
          The pipeline will research the company, score ICP fit, draft an email, and
          self-evaluate it before anything is sent.
        </p>

        <form className="card form" onSubmit={onSubmit}>
          <label className="field">
            <span>Company name</span>
            <input
              value={lead.company_name}
              onChange={(e) => update('company_name', e.target.value)}
              placeholder="Acme Corp"
              required
            />
          </label>

          <label className="field">
            <span>Website URL</span>
            <input
              type="url"
              value={lead.website}
              onChange={(e) => update('website', e.target.value)}
              placeholder="https://acme.com"
              required
            />
          </label>

          <label className="field">
            <span>ICP notes</span>
            <textarea
              value={lead.icp_notes}
              onChange={(e) => update('icp_notes', e.target.value)}
              placeholder="B2B SaaS, 50–200 employees, engineering-led buying…"
              rows={4}
              required
            />
          </label>

          <label className="field">
            <span>Recipient email</span>
            <input
              type="email"
              value={lead.recipient_email}
              onChange={(e) => update('recipient_email', e.target.value)}
              placeholder="founder@acme.com"
              required
            />
          </label>

          {error && <div className="error-text">{error}</div>}

          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? 'Starting…' : 'Start run'}
          </button>
        </form>
      </main>
    </div>
  )
}
