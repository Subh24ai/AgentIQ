import { useMemo, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register } from '../api'
import AuthLayout from '../components/AuthLayout'
import Logo from '../components/Logo'
import PasswordInput from '../components/PasswordInput'

const MIN_PASSWORD_LENGTH = 8

/** Score a password 0–4 from length + character variety. */
function scorePassword(pw: string): number {
  if (!pw) return 0
  let score = 0
  if (pw.length >= MIN_PASSWORD_LENGTH) score++
  if (pw.length >= 12) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++
  return Math.min(score, 4)
}

const STRENGTH = [
  { label: '', cls: '' },
  { label: 'Weak', cls: 'weak' },
  { label: 'Fair', cls: 'medium' },
  { label: 'Good', cls: 'medium' },
  { label: 'Strong', cls: 'strong' },
] as const

export default function RegisterPage(): JSX.Element {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const score = useMemo(() => scorePassword(password), [password])
  const strength = STRENGTH[score]
  const segCls = score <= 1 ? 'on-weak' : score <= 3 ? 'on-medium' : 'on-strong'

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault()
    setError('')
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`)
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      await register(email, password)
      // Two-step flow: account created, now send them to sign in.
      navigate('/', { state: { registered: email } })
    } catch (err) {
      const msg = (err as Error).message
      setError(msg.includes('409') ? 'That email is already registered' : 'Registration failed')
    } finally {
      setBusy(false)
    }
  }

  const mismatch = confirm.length > 0 && confirm !== password

  return (
    <AuthLayout>
      <form className="card auth-card" onSubmit={onSubmit}>
        <div className="auth-lockup">
          <Logo size={28} />
          <span className="brand">
            Agent<span className="brand-accent">IQ</span>
          </span>
        </div>
        <p className="auth-subtitle">Create your account to get started.</p>

        {error && (
          <div className="auth-alert error">
            <span aria-hidden>⚠</span>
            <span>{error}</span>
          </div>
        )}

        <label className="field" htmlFor="reg-email">
          <span>Email</span>
          <input
            id="reg-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="you@company.com"
            required
          />
        </label>

        <label className="field" htmlFor="reg-pw">
          <span>Password</span>
          <PasswordInput
            id="reg-pw"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            placeholder="At least 8 characters"
            minLength={MIN_PASSWORD_LENGTH}
          />
          {password.length > 0 && (
            <>
              <div className="pw-meter" aria-hidden>
                {[0, 1, 2, 3].map((i) => (
                  <span key={i} className={`pw-seg ${i < score ? segCls : ''}`} />
                ))}
              </div>
              <div className={`pw-label ${strength.cls}`}>{strength.label} password</div>
            </>
          )}
        </label>

        <label className="field" htmlFor="reg-confirm">
          <span>Confirm password</span>
          <PasswordInput
            id="reg-confirm"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            placeholder="Re-enter your password"
          />
          {mismatch && <div className="pw-label weak">Passwords don’t match</div>}
        </label>

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />}
          {busy ? 'Creating account…' : 'Create account'}
        </button>

        <p className="auth-foot">
          Already have an account? <Link className="auth-link" to="/">Sign in</Link>
        </p>
      </form>
    </AuthLayout>
  )
}
