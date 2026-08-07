import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'

const MATRIX: [string, string, string, string, string][] = [
  ['Read any page, published or draft', 'y', 'y', 'y', 'y'],
  ['Create a page in its own folders', 'n', 'y', 'y', 'y'],
  ['Edit and save a draft', 'n', 'y', 'y', 'y'],
  ['Publish, so the public sees it', 'n', 'n', 'y', 'y'],
  ['Add, move or delete a folder', 'n', 'n', 'n', 'y'],
  ['Change roles and settings', 'n', 'n', 'n', 'y'],
]

export default function Rights({ d }: { d: Data }) {
  const [q, setQ] = useState('')
  const owning = useMemo(
    () =>
      d.plan.folders
        .filter(f => f.own_permissions === 'yes')
        .sort((a, b) => a.new_path.localeCompare(b.new_path)),
    [d],
  )
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return owning
    return owning.filter(f =>
      (f.new_path + ' ' + f.managed_by + ' ' + f.can_create_and_edit).toLowerCase().includes(t),
    )
  }, [owning, q])

  return (
    <section>
      <h2>Who can create, read, update and publish</h2>
      <p className="lede">
        AKU already runs a two-step workflow: a <b>CW</b> (content writer) group drafts and a{' '}
        <b>CA</b> (content approver) group publishes. That split carries straight over. Permissions
        are hierarchical — whoever holds one on a folder manages that folder <i>and everything
        under it</i>. An admin at the root manages everything; a team on a department manages only
        that department.
      </p>

      <h3>What each role can do</h3>
      <table>
        <thead>
          <tr>
            <th>Action</th>
            <th>Viewer</th>
            <th>Editor</th>
            <th>Publisher</th>
            <th>Admin</th>
          </tr>
        </thead>
        <tbody>
          {MATRIX.map(([label, ...cells]) => (
            <tr key={label}>
              <td>{label}</td>
              {cells.map((c, i) => (
                <td key={i} className={`yn ${c === 'y' ? 'y' : 'n'}`}>
                  {c === 'y' ? '✓' : '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Where a permission is actually set — {owning.length} folders</h3>
      <p className="lede">
        Every other folder inherits from its parent, exactly as SharePoint runs it today.
      </p>
      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a folder or team…"
        />
        <span className="hits">
          {rows.length} of {owning.length} folders
        </span>
      </div>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Folder</th>
              <th>Team that manages it</th>
              <th>Can create &amp; edit</th>
              <th>Can publish</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(f => (
              <tr key={f.new_path}>
                <td>
                  <code>{f.new_path.replace(/^regions\//, '')}</code>
                </td>
                <td>{f.managed_by}</td>
                <td className="ed">
                  <code>{f.can_create_and_edit}</code>
                </td>
                <td className="pub">
                  <code>{f.can_publish}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
