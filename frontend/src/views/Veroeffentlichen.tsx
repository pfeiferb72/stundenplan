import { useEffect, useState } from 'react'
import { api, downloadExport, Me, openExport } from '../api'
import { fachChipStyle } from '../theme'

export default function Veroeffentlichen({ me }: { me: Me }) {
  const [versionen, setVersionen] = useState<any[]>([])
  const [vid, setVid] = useState<number | ''>('')
  const [art, setArt] = useState('klasse')
  const [ziele, setZiele] = useState<any[]>([])
  const [zielId, setZielId] = useState<number | ''>('')
  const [ansicht, setAnsicht] = useState<any>(null)
  const [msg, setMsg] = useState<{ t: string; ok: boolean } | null>(null)
  const [abos, setAbos] = useState<any[]>([])
  const isLeitung = ['schulleitung', 'admin', 'sysadmin'].includes(me.role)

  const load = async () => {
    const v = await api<any[]>('/publish/versionen')
    setVersionen(v)
    if (!vid && v.length) setVid(v[0].id)
    const map: Record<string, string> = { klasse: '/stammdaten/klassen', lehrkraft: '/stammdaten/lehrkraefte', raum: '/stammdaten/raeume', tag: '' }
    if (map[art]) setZiele(await api<any[]>(map[art]))
    else setZiele([0, 1, 2, 3, 4].map((d) => ({ id: d, name: ['Mo', 'Di', 'Mi', 'Do', 'Fr'][d] })))
  }
  useEffect(() => { load() }, [art])
  useEffect(() => {
    if (vid && zielId !== '') api<any>(`/publish/ansicht?art=${art}&ziel_id=${zielId}&version_id=${vid}`).then(setAnsicht).catch((e) => setMsg({ t: e.message, ok: false }))
  }, [vid, zielId, art])

  const setStatus = async (ziel: string) => {
    try {
      await api(`/publish/versionen/${vid}/status?ziel=${ziel}`, { method: 'POST' })
      setMsg({ t: `Status → ${ziel}`, ok: true })
      load()
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }

  const createAbo = async () => {
    const r = await api<any>(`/publish/abos?art=${art}&ziel_id=${zielId}`, { method: 'POST' })
    setAbos([...abos, r])
    setMsg({ t: `Abo erstellt: ${r.ics_url}`, ok: true })
  }

  const exportUrl = (fmt: string) => `/api/export/${fmt}?art=${art}&ziel_id=${zielId}`
  const doExport = async (fmt: string) => {
    try {
      if (fmt === 'html') await openExport(exportUrl('html'))
      else await downloadExport(exportUrl(fmt), `plan-${art}-${zielId}.${fmt}`)
      setMsg({ t: `Export ${fmt.toUpperCase()} geladen (nur ver\u00f6ffentlichte Stunden, FD-704)`, ok: true })
    } catch (e: any) { setMsg({ t: `Export fehlgeschlagen: ${e.message}`, ok: false }) }
  }
  const selected = versionen.find((v) => v.id === vid)

  return (
    <div>
      <h1>Veröffentlichung &amp; Ansichten (FD-701…FD-706)</h1>
      <div className="card row">
        <div><label>Planversion</label>
          <select value={vid} onChange={(e) => setVid(+e.target.value)}>
            {versionen.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.status})</option>)}
          </select>
        </div>
        {selected && (
          <div>
            <label>Workflow (FD-702)</label><br />
            <span className={`badge ${selected.status}`}>{selected.status}</span>
            {selected.status === 'entwurf' && <button onClick={() => setStatus('pruefung')}>→ interne Prüfung</button>}
            {selected.status === 'pruefung' && isLeitung && <button onClick={() => setStatus('freigabe')}>→ Freigabe</button>}
            {selected.status === 'freigabe' && isLeitung && <button onClick={() => setStatus('veroeffentlicht')}>→ Veröffentlichen</button>}
          </div>
        )}
      </div>
      {msg && <div className={msg.ok ? 'ok' : 'error'}>{msg.t}</div>}

      <div className="card row">
        <div><label>Ansicht</label>
          <select value={art} onChange={(e) => { setArt(e.target.value); setZielId('') }}>
            <option value="klasse">Klassenplan</option><option value="lehrkraft">Lehrerplan</option>
            <option value="raum">Raumplan</option><option value="tag">Tagesübersicht</option>
          </select>
        </div>
        <div><label>Ziel</label>
          <select value={zielId} onChange={(e) => setZielId(+e.target.value)}>
            <option value="">– wählen –</option>
            {ziele.map((z) => <option key={z.id} value={z.id}>{z.name ?? `${art} ${z.id}`}{z.nachname ? ` ${z.nachname} ${z.vorname ?? ''}` : ''}</option>)}
          </select>
        </div>
        {zielId !== '' && (
          <>
            <button className="secondary" onClick={() => doExport('pdf')}>PDF (FD-704)</button>
            <button className="secondary" onClick={() => doExport('ics')}>iCalendar</button>
            <button className="secondary" onClick={() => doExport('csv')}>CSV</button>
            <button className="secondary" onClick={() => doExport('html')}>HTML-Widget</button>
            <button className="secondary" onClick={createAbo}>Abo erstellen (FD-705)</button>
          </>
        )}
      </div>

      {abos.length > 0 && (
        <div className="card"><h2>Kalender-Abos</h2>
          {abos.map((a, i) => <div key={i} className="small">ICS-URL: <code>{a.ics_url}</code></div>)}
        </div>
      )}

      {ansicht && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <h2>Ansicht: {art} {zielId} – Version {ansicht.version_id} ({ansicht.status})</h2>
          <table className="grid">
            <thead><tr><th className="cell-slot">Slot</th>{['Mo', 'Di', 'Mi', 'Do', 'Fr'].map((t) => <th key={t}>{t}</th>)}</tr></thead>
            <tbody>
              {Array.from({ length: 8 }, (_, slot) => (
                <tr key={slot}>
                  <td className="cell-slot">{slot + 1}</td>
                  {[0, 1, 2, 3, 4].map((day) => {
                    const z = ansicht.zellen.find((x: any) => x.wochentag === day && x.slot === slot)
                    return (
                      <td key={day}>
                        {z?.eintraege.map((e: any) => (
                          <div key={e.stunde_id} className={`stunde ${e.zustand}`} style={fachChipStyle(e.fach)}>
                            {e.fach} {e.klasse !== '?' ? e.klasse : ''} {e.raum}<br /><span className="small">{e.lehrkraft}</span>
                          </div>
                        ))}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
