import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { CAMPUS } from '../lib/types'

const CAPS = ['admin', 'publisher', 'editor', 'viewer']

export default function People({ d }: { d: Data }) {
  const [q, setQ] = useState('')
  const [cap, setCap] = useState('')
  const [openWho, setOpenWho] = useState<string>('')

  const byCap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const p of d.people) m[p.top_capability] = (m[p.top_capability] || 0) + 1
    return m
  }, [d])

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return d.people.filter(p => {
      if (cap && p.top_capability !== cap) return false
      if (!t) return true
      return (
        p.name + ' ' + p.email + ' ' + p.storyblok_roles.join(' ') + ' ' + p.groups.join(' ')
      ).toLowerCase().includes(t)
    })
  }, [d, q, cap])

  return (
    <section>
      <h2>Every person, and the role to give them</h2>
      <p className="lede">
        {d.people.length} named people hold a permission on aku.edu today. This is what each
        should get in Storyblok, worked out from the groups they are already in. Click a row to
        see exactly which folders they can touch.
      </p>
      <div className="tiles">
        {CAPS.filter(c => byCap[c]).map(c => (
          <div className="tile" key={c}>
            <b>{byCap[c]}</b>
            <span>{c}</span>
          </div>
        ))}
      </div>
      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a name, email, role or group — try Ambreen…"
        />
        <span className="hits">
          {rows.length} of {d.people.length} people
        </span>
        <button className={`btn ${cap === '' ? 'on' : ''}`} onClick={() => setCap('')}>Everyone</button>
        {CAPS.filter(c => byCap[c]).map(c => (
          <button key={c} className={`btn ${cap === c ? 'on' : ''}`} onClick={() => setCap(c)}>
            {c}s
          </button>
        ))}
      </div>
      <div className="plist">
        {rows.slice(0, 400).map(p => {
          const isOpen = openWho === p.login
          return (
            <div key={p.login}>
              <div className="prsn" onClick={() => setOpenWho(isOpen ? '' : p.login)}>
                <div className={`av ${p.top_capability}`}>
                  {p.name.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'}
                </div>
                <div className="pi">
                  <b>{p.name}</b>
                  <span>{p.email || p.login}</span>
                </div>
                <span className="cmp">{CAMPUS[p.campus] || p.campus}</span>
                <span className={`cap2 ${p.top_capability}`}>{p.top_capability}</span>
                <span className="rls">
                  {p.storyblok_roles.length
                    ? p.storyblok_roles.map(r => <span className="rl" key={r}>{r}</span>)
                    : <span className="rl dim">none yet</span>}
                </span>
                <span className="fld">
                  {p.folders.length
                    ? `${p.folders.length} folder${p.folders.length === 1 ? '' : 's'}`
                    : p.top_capability === 'admin' ? 'whole space' : '—'}
                </span>
              </div>
              {isOpen && (
                <div className="pdet">
                  <div className="pdcol">
                    <h4>SharePoint groups today</h4>
                    <ul>{p.groups.map(g => <li key={g}><code>{g}</code></li>)}</ul>
                  </div>
                  <div className="pdcol">
                    <h4>Storyblok roles to assign</h4>
                    <ul>{p.storyblok_roles.map(r => <li key={r}><code>{r}</code></li>)}</ul>
                  </div>
                  <div className="pdcol wide">
                    <h4>
                      Folders they can work in
                      {p.grants.length > 12 ? ` — first 12 of ${p.grants.length}` : ''}
                    </h4>
                    <ul>
                      {p.grants.slice(0, 12).map(g => (
                        <li key={g.folder}>
                          <span className={`gcap ${g.capability}`}>{g.capability}</span>
                          <code>{g.folder.replace(/^regions\//, '')}</code>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )
        })}
        {rows.length > 400 && (
          <div className="more">
            Showing the first 400 of {rows.length} — narrow the search to see the rest.
          </div>
        )}
      </div>
    </section>
  )
}
