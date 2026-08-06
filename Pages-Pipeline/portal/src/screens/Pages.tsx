import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { strip } from '../lib/types'

const FILTERS = [
  { id: '', label: 'All' },
  { id: 'event', label: 'Events' },
  { id: 'blog', label: 'Blogs' },
  { id: 'news', label: 'News' },
  { id: 'update', label: 'Needs updating' },
  { id: 'moved', label: 'Moved to a hub' },
]

export default function Pages({ d }: { d: Data }) {
  const [q, setQ] = useState('')
  const [f, setF] = useState('')

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return d.livePages.filter(p => {
      if (f === 'update' && p.action !== 'Update and move') return false
      if (f === 'moved' && !p.moved_from) return false
      if (f && f !== 'update' && f !== 'moved' && p.content_type !== f) return false
      if (!t) return true
      return (
        p.current_url + ' ' + p.new_path + ' ' + p.managed_by + ' ' + p.entity + ' ' + p.region
      ).toLowerCase().includes(t)
    })
  }, [d, q, f])

  return (
    <section>
      <h2>Every page, old slug and new slug</h2>
      <p className="lede">
        All {d.livePages.length.toLocaleString()} pages. The grey slug is where it lives today;
        the green slug is where it will live. No domain — add your dev or live base URL when you
        deploy.
      </p>
      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a slug, entity, team or type…"
        />
        <span className="hits">
          {rows.length.toLocaleString()} of {d.livePages.length.toLocaleString()} pages
        </span>
        {FILTERS.map(x => (
          <button
            key={x.id}
            className={`btn ${f === x.id ? 'on' : ''}`}
            onClick={() => setF(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>
      <div className="plist">
        <div className="phead">
          <span className="ct">type</span>
          <span className="col">old slug, on aku.edu today</span>
          <span className="col">new slug, in Storyblok</span>
          <span className="pmeta">managed by</span>
          <span className="pact">action</span>
        </div>
        {rows.slice(0, 1500).map(p => (
          <div className="prow" key={p.current_url}>
            <span className={`ct ${p.content_type}`}>{p.content_type}</span>
            <code className="col old">{strip(p.current_url)}</code>
            <code className="col new">{strip(p.new_url)}</code>
            <span className="pmeta">
              {p.managed_by.includes('central') ? <i>inherited</i> : p.managed_by}
              {p.moved_from && <em title={`was ${p.moved_from}`}> · moved to hub</em>}
            </span>
            <span className={`pact ${p.action === 'Update and move' ? 'u' : ''}`}>
              {p.action === 'Update and move' ? 'update first' : 'move as is'}
            </span>
          </div>
        ))}
        {rows.length > 1500 && (
          <div className="more">
            Showing the first 1,500 of {rows.length.toLocaleString()} — narrow the search to see
            the rest.
          </div>
        )}
      </div>

      <h3>{d.dropped.length} pages are not migrating</h3>
      <div className="tw2">
        <table>
          <thead><tr><th>Page</th><th>Why</th></tr></thead>
          <tbody>
            {d.dropped.map(p => (
              <tr key={p.current_url}>
                <td><code>{strip(p.current_url)}</code></td>
                <td>{p.do_not_migrate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
