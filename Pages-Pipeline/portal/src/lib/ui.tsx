/** The controls the folder tree and the org chart both use, so a filter behaves
 *  the same on either screen and the drawer can be opened from both. */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Person } from './types'
import { CAMPUS } from './types'

/** What the detail drawer is showing. `id` is a folder path, a page's current_url,
 *  or a person's login. */
export type Sel =
  | { t: 'folder'; id: string }
  | { t: 'page'; id: string }
  | { t: 'person'; id: string }
  | null

export function Select({
  label, value, onChange, options, width,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { v: string; l: string }[]
  width?: number
}) {
  return (
    <label className="sel" style={width ? { minWidth: width } : undefined}>
      <span>{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}>
        {options.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </label>
  )
}

export function Toggle({
  on, onChange, children,
}: { on: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="tg">
      <input type="checkbox" checked={on} onChange={e => onChange(e.target.checked)} />
      {children}
    </label>
  )
}

/** Type-ahead over 584 people. A <select> that long is unusable, and a datalist
 *  gives no control over what a match looks like. */
export function PersonPicker({
  people, value, onPick,
}: { people: Person[]; value: string; onPick: (login: string) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const picked = useMemo(() => people.find(p => p.login === value), [people, value])

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  const hits = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return people.slice(0, 40)
    return people
      .filter(p => (p.name + ' ' + p.email + ' ' + p.groups.join(' ')).toLowerCase().includes(t))
      .slice(0, 40)
  }, [people, q])

  if (picked) {
    return (
      <div className="ppick on">
        <span className={`av sm ${picked.top_capability}`}>
          {picked.name.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'}
        </span>
        <b>{picked.name}</b>
        <span className={`cap2 ${picked.top_capability}`}>{picked.top_capability}</span>
        <button className="x" onClick={() => { onPick(''); setQ('') }} title="Stop focusing on this person">
          ✕
        </button>
      </div>
    )
  }

  return (
    <div className="ppick" ref={box}>
      <input
        type="search"
        value={q}
        placeholder="Focus on a person — type a name…"
        onChange={e => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
      />
      {open && hits.length > 0 && (
        <div className="pdrop">
          {hits.map(p => (
            <div
              key={p.login}
              className="pdrow"
              onClick={() => { onPick(p.login); setOpen(false) }}
            >
              <span className={`av sm ${p.top_capability}`}>
                {p.name.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'}
              </span>
              <b>{p.name}</b>
              <span className="pd-mail">{p.email || CAMPUS[p.campus] || p.campus}</span>
              <span className={`cap2 ${p.top_capability}`}>{p.top_capability}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export const initials = (n: string) =>
  n.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'
