import type { Data } from '../lib/store'

export default function Shared({ d }: { d: Data }) {
  const shared = d.plan.folders
    .filter(f => f.also_belongs_to)
    .sort((a, b) => a.new_path.localeCompare(b.new_path))
  const moved = d.livePages
    .filter(p => p.moved_from)
    .sort(
      (a, b) =>
        a.content_type.localeCompare(b.content_type) || a.new_path.localeCompare(b.new_path),
    )

  return (
    <section>
      <h2>Shared content, and how tags keep it straight</h2>
      <p className="lede">
        A folder gives a page one home. Some content belongs to more than one owner, so the second
        owner is carried as a tag — which is what lets a page appear in two places without being
        copied.
      </p>

      <h3>{shared.length} folders belong to an entity they cannot live under</h3>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Folder</th>
              <th>Team that manages it</th>
              <th>Also belongs to</th>
            </tr>
          </thead>
          <tbody>
            {shared.map(f => (
              <tr key={f.new_path}>
                <td>
                  <code>{f.new_path.replace(/^regions\//, '')}</code>
                </td>
                <td>{f.managed_by}</td>
                <td>
                  <code>{f.also_belongs_to}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>{moved.length} pages moved into the global hubs</h3>
      <p className="lede">
        Each faculty kept its own events and blog folders. <code>aku.edu/news</code> is already one
        hub that filters by <b>Entity</b> and <b>Tag</b>, so these consolidate and carry their
        region, entity and department as tags. {d.dropped.length - 3} duplicate listing pages and
        detail templates were dropped rather than moved — one hub needs one of each, not one per
        faculty.
      </p>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Was in</th>
              <th>Now in</th>
            </tr>
          </thead>
          <tbody>
            {moved.map(p => (
              <tr key={p.current_url}>
                <td>
                  <span className={`ct ${p.content_type}`}>{p.content_type}</span>
                </td>
                <td>
                  <code>{p.moved_from.replace(/^regions\//, '')}</code>
                </td>
                <td>
                  <code>{p.new_path.replace(/^regions\//, '')}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
