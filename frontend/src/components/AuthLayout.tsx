import type { JSX, ReactNode } from 'react'
import Logo from './Logo'

const STAGES = [
  { icon: '🔍', title: 'Researcher', sub: 'Searches & scrapes the web' },
  { icon: '📊', title: 'Analyst', sub: 'Scores ICP fit & hooks' },
  { icon: '✍️', title: 'Drafter', sub: 'Writes a personalized email' },
  { icon: '⚖️', title: 'Evaluator', sub: 'Adversarial quality judge' },
  { icon: '✓', title: 'Human review', sub: 'You approve before it sends', gate: true },
]

/** Two-panel auth shell: brand + animated pipeline on the left, the form on the right. */
export default function AuthLayout({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="auth-shell">
      <aside className="auth-hero">
        <div className="auth-lockup auth-hero-brand">
          <Logo size={32} />
          <span className="brand">
            Agent<span className="brand-accent">IQ</span>
          </span>
        </div>

        <h1 className="auth-hero-title">
          Autonomous B2B outreach, <span className="grad">with a human in the loop.</span>
        </h1>
        <p className="auth-hero-sub">
          Research a company, score ICP fit, draft a personalized email, and self-evaluate
          it — then approve before it ever sends.
        </p>

        <div className="pipeline-preview" aria-hidden>
          {STAGES.map((s) => (
            <div key={s.title} className={`pp-row${s.gate ? ' gate' : ''}`}>
              <span className="pp-icon">{s.icon}</span>
              <span className="pp-text">
                <span className="pp-title">{s.title}</span>
                <span className="pp-sub">{s.sub}</span>
              </span>
            </div>
          ))}
        </div>
      </aside>

      <main className="auth-form-pane">{children}</main>
    </div>
  )
}
