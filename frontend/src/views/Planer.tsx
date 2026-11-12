import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { fachChipStyle } from '../theme'

const TAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr']

export default function Planer() {
  const [versionen, setVersionen] = useState<any[]>([])
  const [version, setVersion] = useState<any>(null)
  const [stunden, setStunden] = useState<any[]>([])
  const [klassen, setKlassen] = useState<any[]>([])
  const [klasseId, setKlasseId] = useState<number | ''>('')
  const [veranstaltungen, setVeranstaltungen] = useState<any[]>([])
  const [lehrkraefte, setLehrkraefte] = useState<any[]>([])
  const [raeume, setRaeume] = useState<any[]>([])
  const [config, setConfig] = useState<any>(null)
  const [gegenstaende, setGegenstaende] = useState<any[]>([])
  const [slots, setSlots] = useState(8)
  const [runs, setRuns] = useState<any[]>([])
  const [activeRun, setActiveRun] = useState<any>(null)
  const [budget, setBudget] = useState(30)
  const [msg, setMsg] = useState<{ t: string; ok: boolean } | null>(null)
  const [validate, setValidate] = useState<any>(null)
  const [drag, setDrag] = useState<{ stunde: any } | null>(null)
  const [dropCell, setDropCell] = useState<string>('')

  const loadBase = useCallback(async () => {
    const [v, k, lk, r, schule, g] = await Promise.all([
      api<any[]>('/plan/versionen'), api<any[]>('/stammdaten/klassen'),
      api<any[]>('/stammdaten/lehrkraefte'), api<any[]>('/stammdaten/raeume'),
      api<any>('/stammdaten/schule'), api<any[]>('/stammdaten/gegenstaende'),
    ])
    setVersionen(v)
    setKlassen(k)
    setLehrkraefte(lk)
    setRaeume(r)
    setGegenstaende(g)
    setConfig(schule.config)
    setSlots(schule.config?.slots_pro_tag ?? 8)
    if (k.length && klasseId === '') setKlasseId(k[0].id)
    if (v.length && !version) selectVersion(v[0])
    setRuns(await api<any[]>('/plan/solver/runs'))
  }, [])

  const selectVersion = async (v: any) => {
    setVersion(v)
    setValidate(null)
    setStunden(await api<any[]>(`/plan/versionen/${v.id}/stunden`))
    setVeranstaltungen(await api<any[]>(`/veranstaltungen?schuljahr_id=${v.schuljahr_id}`))
  }

  useEffect(() => { loadBase() }, [loadBase])

  // Solver-Polling
  useEffect(() => {
    if (!activeRun) return
    const t = setInterval(async () => {
      const r = await api<any>(`/plan/solver/runs/${activeRun.id}`)
      setActiveRun(r)
      if (['done', 'failed', 'aborted'].includes(r.status)) {
        clearInterval(t)
        setRuns(await api<any[]>('/plan/solver/runs'))
        if (r.status === 'done') {
          const v = await api<any>(`/plan/versionen/${r.ergebnis_version_id}`)
          setVersionen((vs) => [v, ...vs])
          await selectVersion(v)
          setMsg({ t: `Solver fertig. Score: ${r.ergebnis_score}`, ok: true })
        } else setMsg({ t: `Solver ${r.status}: ${r.fehler ?? ''}`, ok: false })
      }
    }, 1000)
    return () => clearInterval(t)
  }, [activeRun?.id])

  const startSolver = async () => {
    setMsg(null)
    const body: any = { schuljahr_id: version.schuljahr_id, zeitbudget_s: budget, seed: Date.now() % 100000 }
    if (version) body.ziel_version_id = version.id
    const r = await api<any>('/plan/solver/runs', { method: 'POST', body: JSON.stringify(body) })
    setActiveRun(r)
  }

  const abortSolver = async () => {
    if (activeRun) await api(`/plan/solver/runs/${activeRun.id}/abort`, { method: 'POST' })
  }

  const doValidate = async () => setValidate(await api(`/plan/versionen/${version.id}/validate`))
  const undo = async () => {
    try {
      await api(`/plan/versionen/${version.id}/undo`, { method: 'POST' })
      setStunden(await api<any[]>(`/plan/versionen/${version.id}/stunden`))
    } catch (e: any) { setMsg({ t: e.message, ok: false }) }
  }
  const newVersion = async () => {
    const r = await api<any>('/plan/versionen', {
      method: 'POST',
      body: JSON.stringify({ schuljahr_id: version.schuljahr_id, name: `Variante ${versionen.length + 1}`, basis_version_id: version.id }),
    })
    setVersionen([r, ...versionen])
    await selectVersion(r)
  }

  const vById = useMemo(() => Object.fromEntries(veranstaltungen.map((v) => [v.id, v])), [veranstaltungen])
  const gById = useMemo(() => Object.fromEntries(gegenstaende.map((g) => [g.id, g])), [gegenstaende])
  const lkById = useMemo(() => Object.fromEntries(lehrkraefte.map((l) => [l.id, l])), [lehrkraefte])
  const raumById = useMemo(() => Object.fromEntries(raeume.map((r) => [r.id, r])), [raeume])

  // Grid: Zeilen = Slots, Spalten = Tage; gefiltert auf gewählte Klasse
  const zellen = useMemo(() => {
    const map: Record<string, any[]> = {}
    for (const s of stunden) {
      const v = vById[s.veranstaltung_id]
      if (!v || (klasseId !== '' && v.klasse_id !== klasseId)) continue
      for (let sl = s.slot; sl < s.slot + s.laenge; sl++) {
        const key = `${s.wochentag}:${sl}`
        ;(map[key] = map[key] || []).push(s)
      }
    }
    return map
  }, [stunden, vById, klasseId])

  const onDrop = async (day: number, slot: number) => {
    if (!drag) return
    const s = drag.stunde
    setDrag(null)
    setDropCell('')
    try {
      await api(`/plan/versionen/${version.id}/stunden/${s.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ wochentag: day, slot }),
      })
      setStunden(await api<any[]>(`/plan/versionen/${version.id}/stunden`))
      setMsg({ t: `Stunde verschoben nach ${TAGE[day]} Slot ${slot}`, ok: true })
    } catch (e: any) {
      setMsg({ t: `Blockiert (FD-204): ${e.message}`, ok: false })
    }
  }

  return (
    <div>
      <h1>Planer (FD-301…FD-310)</h1>
      <div className="card row">
        <div>
          <label>Planversion</label>
          <select value={version?.id ?? ''} onChange={(e) => selectVersion(versionen.find((v) => v.id === +e.target.value))}>
            {versionen.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.status}, Score {Math.round(v.score)})</option>)}
          </select>
        </div>
        <div>
          <label>Klasse</label>
          <select value={klasseId} onChange={(e) => setKlasseId(+e.target.value)}>
            <option value="">alle</option>
            {klassen.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
        </div>
        <button onClick={newVersion}>+ Variante aus Basis (FD-306)</button>
        <button className="secondary" onClick={undo}>Undo (FD-307)</button>
        <button className="secondary" onClick={doValidate}>Validieren (FD-209)</button>
        <div>
          <label>Solver-Zeitbudget (s)</label>
          <input type="number" value={budget} min={5} max={900} onChange={(e) => setBudget(+e.target.value)} style={{ width: 80 }} />
        </div>
        <button onClick={startSolver} disabled={!version || !!activeRun}>Solver starten (FD-302)</button>
        {activeRun && <button className="danger" onClick={abortSolver}>Abbrechen</button>}
      </div>

      {msg && <div className={msg.ok ? 'ok' : 'error'}>{msg.t}</div>}

      {activeRun && (
        <div className="card">
          Solver-Lauf #{activeRun.id}: <b>{activeRun.status}</b> · Fortschritt {(activeRun.progress * 100).toFixed(0)} %
          <div className="progress"><div style={{ width: `${activeRun.progress * 100}%` }} /></div>
        </div>
      )}

      {validate && (
        <div className="card">
          <b>Konfliktübersicht:</b> {validate.harte_verletzungen.length} harte, {validate.weiche_verletzungen.length} weiche Verletzungen · Score {Math.round(validate.score)}
          {validate.harte_verletzungen.slice(0, 10).map((h: any, i: number) => (
            <div key={i} className="error">{h.message ?? h.code}</div>
          ))}
          {validate.weiche_verletzungen.slice(0, 10).map((w: any, i: number) => (
            <div key={i} className="warn">{w.code}: {w.block ?? w.klasse_id ?? w.lehrkraft_id} (Gewicht {w.gewicht})</div>
          ))}
        </div>
      )}

      {version && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table className="grid">
            <thead>
              <tr><th className="cell-slot">Slot</th>{TAGE.map((t, d) => <th key={d}>{t}</th>)}</tr>
            </thead>
            <tbody>
              {Array.from({ length: slots }, (_, slot) => (
                <tr key={slot}>
                  <td className="cell-slot">{slot + 1}</td>
                  {TAGE.map((_, day) => {
                    const key = `${day}:${slot}`
                    const entries = zellen[key] || []
                    return (
                      <td key={key}
                          className={dropCell === key ? 'drop-target' : ''}
                          onDragOver={(e) => { e.preventDefault(); setDropCell(key) }}
                          onDragLeave={() => setDropCell('')}
                          onDrop={(e) => { e.preventDefault(); onDrop(day, slot) }}>
                        {entries.map((s) => {
                          const v = vById[s.veranstaltung_id]
                          const lk = lkById[s.lehrkraft_id]
                          const raum = raumById[s.raum_id]
                          const fach = v ? (gById[v.gegenstand_id]?.code ?? '?') : '?'
                          return (
                            <div key={s.id} className={`stunde ${s.zustand} ${s.fixiert ? 'fixiert' : ''}`} draggable
                                 onDragStart={() => setDrag({ stunde: s })}
                                 style={fachChipStyle(fach)}
                                 title={`${fach} · ${raum?.name ?? ''} · ${lk ? lk.nachname : ''} · ${s.zustand}`}>
                              {fach} · {raum?.name ?? ''}<br />
                              <span className="small">{lk?.nachname ?? ''}</span>
                            </div>
                          )
                        })}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small">Drag &amp; Drop = Platzierung mit Echtzeit-Validierung (harte Restriktionen blockieren, FD-301).</p>
        </div>
      )}

      <div className="card">
        <h2>Solver-Läufe</h2>
        <table className="data">
          <thead><tr><th>ID</th><th>Status</th><th>Fortschritt</th><th>Score</th><th>Ergebnis-Version</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td><td>{r.status}</td><td>{(r.progress * 100).toFixed(0)} %</td>
                <td>{r.ergebnis_score != null ? Math.round(r.ergebnis_score) : '–'}</td>
                <td>{r.ergebnis_version_id ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
