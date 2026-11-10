import { useEffect, useState } from 'react'
import { api } from '../api'

type Row = Record<string, any>

export default function Stammdaten() {
  const [tab, setTab] = useState('klassen')
  const [data, setData] = useState<Row[]>([])
  const [msg, setMsg] = useState<{ t: string; ok: boolean } | null>(null)
  const [schuljahre, setSchuljahre] = useState<Row[]>([])
  const [importBericht, setImportBericht] = useState<any>(null)

  const load = async (t: string) => {
    setMsg(null)
    const map: Record<string, string> = {
      klassen: '/stammdaten/klassen', lehrkraefte: '/stammdaten/lehrkraefte',
      gegenstaende: '/stammdaten/gegenstaende', raeume: '/stammdaten/raeume',
      stundentafeln: '/stammdaten/stundentafeln', schuljahre: '/stammdaten/schuljahre',
    }
    try {
      setData(await api<Row[]>(map[t]))
      if (t === 'klassen' || t === 'schuljahre') setSchuljahre(await api<Row[]>('/stammdaten/schuljahre'))
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }
  useEffect(() => { load(tab) }, [tab])

  const generate = async () => {
    const sj = schuljahre[0]
    if (!sj) return
    const r = await api<any>(`/veranstaltungen/generieren/${sj.id}`, { method: 'POST' })
    setMsg({ t: `Veranstaltungen erzeugt: ${r.erzeugt}`, ok: true })
  }

  const onImport = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    const token = localStorage.getItem('spps_token')
    const res = await fetch('/api/stammdaten/import/smls', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
    setImportBericht(await res.json())
  }

  const cols: Record<string, string[]> = {
    klassen: ['id', 'name', 'jahrgang', 'schuelerzahl', 'teilungsgruppe'],
    lehrkraefte: ['id', 'nachname', 'vorname', 'email', 'lehrverpflichtung', 'max_tagesstunden', 'qualifikationen'],
    gegenstaende: ['id', 'code', 'name', 'schulart', 'benoetigt_fachraum'],
    raeume: ['id', 'name', 'kapazitaet', 'fachraum', 'ausstattung'],
    stundentafeln: ['id', 'schulart', 'jahrgang', 'gegenstand_id', 'wochenstunden', 'aufteilung', 'rhythmus'],
    schuljahre: ['id', 'bezeichnung', 'start', 'ende', 'aktiv'],
  }

  return (
    <div>
      <h1>Stammdaten (FD-101…FD-109)</h1>
      <div className="tabs">
        {Object.keys(cols).map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {msg && <div className={msg.ok ? 'ok' : 'error'}>{msg.t}</div>}
      {tab === 'klassen' && (
        <div className="card">
          <button onClick={generate}>Unterrichtsveranstaltungen aus Stundentafel generieren (FD-202)</button>
          <div className="row" style={{ marginTop: 8 }}>
            <div>
              <label>SMLS-CSV-Import (SS-10, FD-109)</label>
              <input type="file" accept=".csv" onChange={(e) => e.target.files?.[0] && onImport(e.target.files[0])} />
            </div>
          </div>
          {importBericht && (
            <div className="warn">Import: {importBericht.importiert} neu, {importBericht.aktualisiert} aktualisiert,
              {importBericht.konflikte.length} Konflikte {importBericht.konflikte.length > 0 && JSON.stringify(importBericht.konflikte)}</div>
          )}
        </div>
      )}
      <div className="card">
        <table className="data">
          <thead><tr>{cols[tab].map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={r.id ?? i}>{cols[tab].map((c) => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
