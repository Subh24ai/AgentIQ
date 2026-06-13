import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'
import { setToken } from '../auth'

export default function LoginPage(): JSX.Element {
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const token = await login(username, password)
      // Store in sessionStorage (not localStorage) to limit the XSS exposure
      // window — token dies with the tab. See src/auth.ts.
      setToken(token)
      navigate('/dashboard')
    } catch {
      setError('Invalid username or password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="card auth-card" onSubmit={onSubmit}>
        <div className="brand">
          Agent<span className="brand-accent">IQ</span>
        </div>
        <p className="muted">Autonomous B2B outreach control plane</p>

        <label className="field">
          <span>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <div className="error-text">{error}</div>}

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="hint">Dev users: admin / reviewer</p>
      </form>
    </div>
  )
}
