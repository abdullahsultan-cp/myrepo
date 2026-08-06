import type { Data } from '../lib/store'

export default function Overview({ d }: { d: Data }) {
  const F = d.plan.folders
  const countKind = (prefix: string, kind: string) =>
    F.filter(f => f.kind === kind && (f.new_path === prefix || f.new_path.startsWith(prefix + '/'))).length

  const regions = F.filter(f => f.kind === 'region' && f.new_path.split('/').length === 2)
    .sort((a, b) => (a.new_path === 'regions/global' ? -1 : b.new_path === 'regions/global' ? 1 : a.new_path.localeCompare(b.new_path)))

  const moved = d.livePages.filter(p => p.moved_from).length
  const byType: Record<string, number> = {}
  for (const p of d.livePages) byType[p.content_type] = (byType[p.content_type] || 0) + 1

  const tiles: [string, string, boolean][] = [
    [d.livePages.length.toLocaleString(), 'pages to migrate', true],
    [String(F.length), 'folders to create', false],
    [String(regions.length), 'regions incl. global', false],
    [String(countKind('regions', 'entity')), 'entity placements', false],
    [String(countKind('regions', 'department')), 'departments', false],
    [String(d.plan.roles.length), 'roles to create', true],
    [String(d.people.length), 'people to place', false],
    [String(d.dropped.length), 'pages dropped', false],
  ]

  return (
    <section>
      <h2>What is changing</h2>
      <p className="lede">
        Two AKU exports drive this. <b>aku-university-visible-pages.csv</b> is AKU&rsquo;s own list
        of what to migrate. <b>The SharePoint permissions export</b> says who owns and edits each
        folder today. Everything here comes from those two, confirmed against the live site
        wherever they were silent.
      </p>
      <div className="tiles">
        {tiles.map(([v, l, hl]) => (
          <div className={`tile ${hl ? 'hl' : ''}`} key={l}>
            <b>{v}</b>
            <span>{l}</span>
          </div>
        ))}
      </div>

      <h3>The shape</h3>
      <div className="note g">
        Root holds <b>regions</b> and <b>staging</b>. Global is a region like any other — the one
        that owns what no faculty owns. Inside a region: <b>entities</b> for the faculties, schools
        and institutes AKU itself publishes, plain <b>folders</b> for units it does not, and{' '}
        <b>departments</b> inside an entity.
        <div className="pathline">
          regions / pakistan / entities / medical-college / departments / anaes / home
        </div>
      </div>

      {regions.map(r => {
        const p = r.new_path
        const slug = p.split('/').pop()!
        const ents = countKind(p, 'entity')
        const depts = countKind(p, 'department')
        const rf = countKind(p, 'region-folder')
        const secs = countKind(p, 'section')
        return (
          <div className="card" key={p}>
            <h3 style={{ margin: '0 0 6px' }}>{slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</h3>
            <p style={{ margin: 0, fontSize: 13.5, color: 'var(--ink2)' }}>
              {slug === 'global'
                ? `It holds the ${secs} section folders and ${d.subPages(p).toLocaleString()} pages that no faculty owns — news, events and blogs, plus about us, academics, admissions, research, support us, and the pages for students, alumni, faculty, media, careers and libraries.`
                : `${ents} entit${ents === 1 ? 'y' : 'ies'}${depts ? `, ${depts} departments inside them` : ''}${rf ? `, plus ${rf} folder${rf === 1 ? '' : 's'} of its own that are not entities` : ''}. ${d.subPages(p).toLocaleString()} pages.${r.countries ? ` Its entities work across ${r.countries}.` : ''}`}
            </p>
          </div>
        )
      })}

      <h3>Content type</h3>
      <div className="card">
        <p style={{ margin: 0, fontSize: 13.5 }}>
          Of the {d.livePages.length.toLocaleString()} pages:{' '}
          {Object.entries(byType)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v], i, arr) => (
              <span key={k}>
                <b>{v.toLocaleString()}</b> {k}
                {i < arr.length - 1 ? ', ' : ''}
              </span>
            ))}
          . News, events and blogs all live in the global hubs and carry region, entity and
          department as tags — the same way <code>aku.edu/news</code> already filters by Entity and
          Tag today. <b>{moved}</b> pages were moved into those hubs out of the faculties&rsquo; own
          folders.
        </p>
      </div>
    </section>
  )
}
