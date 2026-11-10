import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Vertretung() {
  const [datum, setDatum] = useState(() => new Date().toISOString().slice(0, 10))
  const [lehrkraefte, setLehrkraefte] = useState<any[]>([])
  const [abwesenheiten, setAbwesenheiten] = useState<any[]>([])
  const [liste, setListe] = useState<any[]>([])
  const [konto, setKonto] = useState<any>({})
  const [lkId, setLkId] = useState<number | ''>('')
  const [typ, setTyp] = useState('krankheit')
  const [msg, setMsg] = useState<{ t: string; ok: boolean } | null>(null)

  const load = async () => {
    setLehrkraefte(await api<any[]>('/stammdaten/lehrkraefte'))
    setAbwesenheiten(await api<any[]>('/vertretung/abwesenheiten'))
    setListe(await api<any[]>(`/vertretung/liste?datum=${datum}`))
    setKonto(await api<any>('/vertretung/konto'))
  }
  useEffect(() => { load() }, [])
  useEffect(() => { api<any[]>(`/vertretung/liste?datum=${datum}`).then(setListe).catch(() => {}) }, [datum])

  const melden = async () => {
    if (!lkId) return
    try {
      const ab = await api<any>('/vertretung/abwesenheiten', {
        method: 'POST', body: JSON.stringify({ lehrkraft_id: lkId, datum, typ, grund: '' }),
      })
      await api(`/vertretung/abwesenheiten/${ab.id}/vorschlaege`, { method: 'POST' })
      setMsg({ t: `Abwesenheit gemeldet + Vertretungsvorschläge erzeugt (FD-501…505)`, ok: true })
      load()
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }

  const veroeffentlichen = async () => {
    try {
      const r = await api<any>(`/vertretung/veroeffentlichen?datum=${datum}`, { method: 'POST' })
      setMsg({ t: `${r.veroeffentlicht} Vertretungen veröffentlicht, ${r.benachrichtigte_user} Personen benachrichtigt (FD-506/801)`, ok: true })
      load()
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }

  return (
    <div>
      <h1>Vertretungsplanung (FD-501…FD-507)</h1>
      <div className="card row">
        <div><label>Datum</label><input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} /></div>
        <div><label>Lehrkraft</label>
          <select value={lkId} onChange={(e) => setLkId(+e.target.value)}>
            <option value="">– wählen –</option>
            {lehrkraefte.map((l) => <option key={l.id} value={l.id}>{l.nachname} {l.vorname}</option>)}
          </select>
        </div>
        <div><label>Typ</label>
          <select value={typ} onChange={(e) => setTyp(e.target.value)}>
            {['krankheit', 'dienstweg', 'fortbildung', 'exkursion', 'freistellung'].map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <button onClick={melden}>Abwesenheit melden + Vorschläge (ein Schritt)</button>
        <button onClick={veroeffentlichen}>Vertretungsplan veröffentlichen (FD-506)</button>
      </div>
      {msg && <div className={msg.ok ? 'ok' : 'error'}>{msg.t}</div>}

      <div className="card">
        <h2>Abwesenheiten</h2>
        <table className="data"><thead><tr><th>ID</th><th>Lehrkraft</th><th>Datum</th><th>Typ</th><th>Grund</th></tr></thead>
          <tbody>{abwesenheiten.map((a) => {
            const lk = lehrkraefte.find((l) => l.id === a.lehrkraft_id)
            return <tr key={a.id}><td>{a.id}</td><td>{lk ? `${lk.nachname} ${lk.vorname}` : a.lehrkraft_id}</td><td>{a.datum}</td><td>{a.typ}</td><td>{a.grund}</td></tr>
          })}</tbody>
        </table>
      </div>

      <div className="card">
        <h2>Vertretungsliste {datum}</h2>
        <table className="data">
          <thead><tr><th>Slot</th><th>Fach</th><th>Klasse</th><th>Original</th><th>Typ (Kaskade FD-503)</th><th>Vertreter:in</th><th>Status</th></tr></thead>
          <tbody>{liste.map((v) => (
            <tr key={v.id}><td>{v.slot}</td><td>{v.fach}</td><td>{v.klasse}</td><td>{v.original}</td><td>{v.typ}</td><td>{v.vertreter ?? '–'}</td><td>{v.status}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <div className="card">
        <h2>Vertretungskonten (FD-507)</h2>
        <table className="data"><thead><tr><th>Lehrkraft</th><th>Vertretungen</th><th>davon Fachvertretung</th></tr></thead>
          <tbody>{Object.entries(konto).map(([name, k]: [string, any]) => (
            <tr key={name}><td>{name}</td><td>{k.vertretungen}</td><td>{k.fachvertretungen}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}
