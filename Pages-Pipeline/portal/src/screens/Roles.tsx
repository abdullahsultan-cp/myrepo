import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'

export default function Roles({ d }: { d: Data }) {
  const [q, setQ] = useState('')
  const R = d.plan.roles

  const caps = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of R) m[r.capability] = (m[r.capability] || 0) + 1
    return m
  }, [R])

  const unscoped = R.filter(r => r.unit !== '(space-wide)' && !r.folders_scoped)

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    const sorted = [...R].sort(
      (a, b) =>
        (a.unit === '(space-wide)' ? 1 : 0) - (b.unit === '(space-wide)' ? 1 : 0) ||
        a.storyblok_role.localeCompare(b.storyblok_role),
    )
    if (!t) return sorted
    return sorted.filter(r =>
      (r.storyblok_role + ' ' + r.unit + ' ' + r.capability + ' ' + r.source_sharepoint_groups)
        .toLowerCase()
        .includes(t),
    )
  }, [R, q])

  return (
    <section>
      <h2>Roles to create, and who goes in them</h2>
      <p className="lede">
        {caps.editor} editor roles and {caps.publisher} publisher roles — one pair per AKU team,
        each limited to the folders that team owns, so Anaesthesiology cannot edit Pathology.{' '}
        <b>People</b> is how many named accounts are in the SharePoint group today.
      </p>
      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a role, team or group…"
        />
        <span className="hits">
          {rows.length} of {R.length} roles
        </span>
      </div>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Storyblok role</th>
              <th>Can</th>
              <th>People</th>
              <th>AKU team</th>
              <th>Folders</th>
              <th>From SharePoint group</th>
              <th>Allowed paths</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.storyblok_role}>
                <td>
                  <code>
                    <b>{r.storyblok_role}</b>
                  </code>
                </td>
                <td className={`cap ${r.capability}`}>{r.capability}</td>
                <td className="num">{r.members || '—'}</td>
                <td>{r.unit}</td>
                <td className="num">{r.folders_scoped || '—'}</td>
                <td>
                  <code className="sm">{r.source_sharepoint_groups}</code>
                </td>
                <td className="sm">{r.allowed_paths.replace(/regions\//g, '') || r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>{unscoped.length} roles still need a scope</h3>
      <div className="note">
        These teams own a section whose folder names no owner — it carries the site-wide group
        roster instead — so there is nothing to derive their folder list from. Someone at AKU has to
        say which folders they cover:{' '}
        <b>{[...new Set(unscoped.map(r => r.unit))].sort().join(', ')}</b>.
      </div>
    </section>
  )
}
