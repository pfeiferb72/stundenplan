import { useEffect, useState } from 'react'
import { api } from '../api'

const ROLLEN = ['planer', 'schulleitung', 'lehrkraft', 'klassenkurator', 'verwaltung', 'schueler', 'admin']

export default function Admin() {
  const [users, setUsers] = useState<any[]>([])
  const [audit, setAudit] = useState<any[]>([])
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState('lehrkraft')
  const [msg, setMsg] = useState<{ t: string; ok: boolean } | null>(null)

  const load = async () => {
    setUsers(await api<any[]>('/admin/benutzer'))
    setAudit(await api<any[]>('/admin/audit?limit=100'))
  }
  useEffect(() => { load() }, [])

  const createUser = async () => {
    try {
      await api('/admin/benutzer', { method: 'POST', body: JSON.stringify({ email, name, role }) })
      setMsg({ t: 'Benutzer angelegt (FD-901)', ok: true })
      setEmail(''); setName('')
      load()
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }

  const exportMandant = async () => {
    const r = await api<any>('/admin/mandant-export')
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'spps-mandant-export.json'
    a.click()
    setMsg({ t: 'Mandanten-Export heruntergeladen (FD-905)', ok: true })
  }

  return (
    <div>
      <h1>Administration (FD-901…FD-905)</h1>
      <div className="card">
        <h2>Benutzer &amp; Rollen (RBAC)</h2>
        <div className="row">
          <input placeholder="E-Mail" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <select value={role} onChange={(e) => setRole(e.target.value)}>{ROLLEN.map((r) => <option key={r}>{r}</option>)}</select>
          <button onClick={createUser}>Anlegen</button>
        </div>
        {msg && <div className={msg.ok ? 'ok' : 'error'}>{msg.t}</div>}
        <table className="data">
          <thead><tr><th>ID</th><th>Name</th><th>E-Mail</th><th>Rolle</th><th>aktiv</th></tr></thead>
          <tbody>{users.map((u) => <tr key={u.id}><td>{u.id}</td><td>{u.name}</td><td>{u.email}</td><td>{u.role}</td><td>{u.aktiv ? 'ja' : 'nein'}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="card">
        <h2>Mandant</h2>
        <button className="secondary" onClick={exportMandant}>Gesamten Mandanten exportieren (DSGVO/Offboarding, FD-905)</button>
      </div>
      <div className="card">
        <h2>Audit-Log (FD-904)</h2>
        <table className="data">
          <thead><tr><th>Zeitpunkt</th><th>Aktion</th><th>Objekt</th><th>Details</th><th>User</th></tr></thead>
          <tbody>{audit.map((a) => (
            <tr key={a.id}><td>{a.zeitpunkt?.replace('T', ' ').slice(0, 19)}</td><td>{a.aktion}</td><td>{a.objekt}</td>
              <td><code>{JSON.stringify(a.details).slice(0, 80)}</code></td><td>{a.user_id}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}
