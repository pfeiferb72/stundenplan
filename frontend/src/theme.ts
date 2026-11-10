import type { CSSProperties } from 'react'

const PALETTE = [
  '#4f46e5', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1',
]

/** Stabile Akzentfarbe je Fach-Code (für Chips im Plan-Grid). */
export function fachColor(code: string): string {
  let h = 0
  for (const c of code || '?') h = (h * 31 + c.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

export function fachChipStyle(code: string): CSSProperties {
  const c = fachColor(code)
  return { borderLeftColor: c, background: c + '1f', color: '#1f2937' }
}
