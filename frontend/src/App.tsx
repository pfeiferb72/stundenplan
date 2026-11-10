import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, Navigate, useNavigate } from 'react-router-dom'
import { api, fetchMe, getToken, Me, setToken } from './api'
import Login from './views/Login'
import Stammdaten from './views/Stammdaten'
import Planer from './views/Planer'
import Vertretung from './views/Vertretung'
import Veroeffentlichen from './views/Veroeffentlichen'
import Admin from './views/Admin'

const PLANER_ROLES = ['planer', 'admin', 'sysadmin', 'schulleitung', 'verwaltung']

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    const hash = window.location.hash
    const m = hash.match(/token=([^&]+)/)
    if (m) {
      setToken(m[1])
      window.location.hash = hash.replace(/[?&]token=[^&]+/, '')
    }
    if (getToken()) {
      fetchMe().then(setMe).catch(() => setToken(null)).finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  if (loading) return <main>Laden…</main>
  if (!me) return <Login onLogin={setMe} />

  const logout = () => { setToken(null); setMe(null); navigate('/login') }
  const isPlaner = PLANER_ROLES.includes(me.role)

  return (
    <>
      <header className="topbar">
        <span className="brand">SPPS</span>
        {isPlaner && <NavLink to="/stammdaten">Stammdaten</NavLink>}
        {isPlaner && <NavLink to="/planer">Planer</NavLink>}
        {isPlaner && <NavLink to="/vertretung">Vertretung</NavLink>}
        <NavLink to="/plaene">Pläne &amp; Exporte</NavLink>
        {(me.role === 'admin' || me.role === 'sysadmin') && <NavLink to="/admin">Administration</NavLink>}
        <span className="user">{me.name} ({me.role}) · <a href="#/login" onClick={logout} style={{ color: '#fff' }}>Abmelden</a></span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to={isPlaner ? '/planer' : '/plaene'} />} />
          <Route path="/login" element={<Navigate to={isPlaner ? '/planer' : '/plaene'} />} />
          <Route path="/stammdaten" element={isPlaner ? <Stammdaten /> : <Navigate to="/plaene" />} />
          <Route path="/planer" element={isPlaner ? <Planer /> : <Navigate to="/plaene" />} />
          <Route path="/vertretung" element={isPlaner ? <Vertretung /> : <Navigate to="/plaene" />} />
          <Route path="/plaene" element={<Veroeffentlichen me={me} />} />
          <Route path="/admin" element={(me.role === 'admin' || me.role === 'sysadmin') ? <Admin /> : <Navigate to="/plaene" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
      <NotificationsBell />
    </>
  )
}

function NotificationsBell() {
  const [n, setN] = useState<any[]>([])
  useEffect(() => {
    api<any[]>('/publish/notifications?nur_ungelesen=true').then(setN).catch(() => {})
  }, [])
  if (!n.length) return null
  return (
    <div style={{ position: 'fixed', right: 12, bottom: 12, maxWidth: 340 }}>
      {n.slice(0, 5).map((x) => (
        <div key={x.id} className="notif ungelesen">{x.titel}<div className="small">{x.text}</div></div>
      ))}
    </div>
  )
}
