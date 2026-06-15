import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { login } from '../api'
import { setToken } from '../auth'
import AuthLayout from '../components/AuthLayout'
import Logo from '../components/Logo'
import PasswordInput from '../components/PasswordInput'

export default function LoginPage(): JSX.Element {
  const navigate = useNavigate()
  const location = useLocation()
  // Set by RegisterPage on a successful sign-up so we can prefill + confirm.
  const registered = (location.state as { registered?: string } | null)?.registered ?? ''
  const [username, setUsername] = useState(registered)
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
    <AuthLayout>
      <form className="card auth-card" onSubmit={onSubmit}>
        <div className="auth-lockup">
          <Logo size={28} />
          <span className="brand">
            Agent<span className="brand-accent">IQ</span>
          </span>
        </div>
        <p className="auth-subtitle">Welcome back — sign in to your control plane.</p>

        {registered && (
          <div className="auth-alert success">
            <span aria-hidden>✓</span>
            <span>Account created for {registered}. Please sign in.</span>
          </div>
        )}
        {error && (
          <div className="auth-alert error">
            <span aria-hidden>⚠</span>
            <span>{error}</span>
          </div>
        )}

        <label className="field" htmlFor="login-id">
          <span>Username or email</span>
          <input
            id="login-id"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            placeholder="you@company.com"
            required
          />
        </label>

        <label className="field" htmlFor="login-pw">
          <span>Password</span>
          <PasswordInput
            id="login-pw"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </label>

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="auth-foot">
          No account? <Link className="auth-link" to="/register">Create one</Link>
        </p>

        <div className="dev-note">
          Demo users: <code>admin</code> / <code>agentiq_admin</code> · <code>reviewer</code> / <code>agentiq_review</code>
        </div>
      </form>
    </AuthLayout>
  )
}
