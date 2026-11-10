export interface Me {
  id: number
  email: string
  name: string
  role: string
  school_id: number | null
  lehrkraft_id: number | null
  klasse_id: number | null
}

const TOKEN_KEY = 'spps_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(opts.headers as any) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`/api${path}`, { ...opts, headers })
  if (res.status === 401 && !path.startsWith('/auth/')) {
    setToken(null)
    window.location.hash = '#/login'
    throw new Error('Nicht authentifiziert')
  }
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `HTTP ${res.status}`)
  }
  return data
}

export async function devLogin(email: string) {
  const r = await api<{ access_token: string; user: Me }>('/auth/dev-login', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
  setToken(r.access_token)
  return r.user
}

export async function fetchMe(): Promise<Me> {
  return api<Me>('/auth/me')
}
