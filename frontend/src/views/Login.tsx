import { useState } from 'react'
import { devLogin, Me } from '../api'

const DEMO_USERS = [
  ['planer@schule.at', 'Planer:in (Vollzugriff)'],
  ['leitung@schule.at', 'Schulleitung (Freigabe)'],
  ['huber@schule.at', 'Lehrkraft'],
  ['1ah@schule.at', 'Klassenkurator:in'],
  ['admin@schule.at', 'Administration'],
]

export default function Login({ onLogin }: { onLogin: (m: Me) => void }) {
  const [email, setEmail] = useState('planer@schule.at')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await devLogin(email))
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-box">
      <h1>SPPS Login</h1>
      <p className="small">Dev-Login (lokale Entwicklung). In Produktion: OIDC über Schul-Identity-Provider (TU-50).</p>
      <form onSubmit={submit}>
        <label>E-Mail</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: '100%' }} />
        <div className="small" style={{ margin: '8px 0' }}>
          {DEMO_USERS.map(([mail, label]) => (
            <div key={mail}><a href="#" onClick={(e) => { e.preventDefault(); setEmail(mail) }}>{mail}</a> – {label}</div>
          ))}
        </div>
        <button type="submit" disabled={busy} style={{ width: '100%', marginTop: 8 }}>{busy ? '…' : 'Anmelden'}</button>
      </form>
      {error && <div className="error">{error}</div>}
    </div>
  )
}
