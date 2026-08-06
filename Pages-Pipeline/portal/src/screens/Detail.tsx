/** The detail drawer. One folder, one page or one person, opened from either the
 *  folder tree or the org chart, and cross-linked so you can walk from a folder
 *  to the people who can edit it to every other page one of them can touch.
 */
import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { CAN, CAP_ORDER, CAP_VERB, type Who } from '../lib/perm'
import { KIND_LABEL, leaf, strip, CAMPUS } from '../lib/types'
import { initials, type Sel } from '../lib/ui'

const CAP_LABEL: Record<string, string> = {
  admin: 'Admins', publisher: 'Publishers', editor: 'Editors',
  structure: 'Structure managers', translator: 'Translators', viewer: 'Viewers',
}

export default function Drawer({
  d, sel, onSel,
}: { d: Data; sel: Sel; onSel: (s: Sel) => void }) {
  if (!sel) return null
  return (
    <>
      <div className="scrim" onClick={() => onSel(null)} />
      <aside className="drw">
        <button className="drw-x" onClick={() => onSel(null)} title="Close">✕</button>
        {sel.t === 'folder' && <FolderPane d={d} path={sel.id} onSel={onSel} />}
        {sel.t === 'page' && <PagePane d={d} url={sel.id} onSel={onSel} />}
        {sel.t === 'person' && <PersonPane d={d} login={sel.id} onSel={onSel} />}
      </aside>
    </>
  )
}

/* ------------------------------------------------------------------ folder */

function FolderPane({ d, path, onSel }: { d: Data; path: string; onSel: (s: Sel) => void }) {
  const f = d.byPath.get(path)
  const [tab, setTab] = useState<'who' | 'pages' | 'why'>('who')
  if (!f) return <div className="drw-b">Folder not found: <code>{path}</code></div>

  const r = d.perm.rightsOf(path)
  const who = d.perm.peopleOf(path)
  const counts = d.perm.countsOf(path)
  const here = d.pagesByFolder.get(path) || []
  const under = d.pagesUnder(path)
  const kids = d.kids.get(path) || []
  const crumbs = path.split('/').map((_, i, a) => a.slice(0, i + 1).join('/'))

  return (
    <>
      <div className="drw-h">
        <div className="drw-crumb">
          {crumbs.map((c, i) => (
            <span key={c}>
              {i > 0 && <i>/</i>}
              {d.byPath.has(c) && c !== path
                ? <a onClick={() => onSel({ t: 'folder', id: c })}>{leaf(c)}</a>
                : <b>{leaf(c)}</b>}
            </span>
          ))}
        </div>
        <h3>{f.title || leaf(path)}</h3>
        <div className="drw-tags">
          <span className={`chip k k-${f.kind}`}>{KIND_LABEL[f.kind] || f.kind}</span>
          {f.region && <span className="chip blue">{f.region}</span>}
          {f.entity && <span className="chip blue">{f.entity}</span>}
          {r.inherited
            ? <span className="chip">inherits permissions</span>
            : <span className="chip green">sets its own permissions</span>}
          {f.also_belongs_to && <span className="chip blue">shared</span>}
          {f.archive_candidate && <span className="chip amber">archive?</span>}
        </div>
        <div className="drw-nums">
          <b>{here.length}</b><span>pages here</span>
          <b>{under.length}</b><span>pages below</span>
          <b>{kids.length}</b><span>subfolders</span>
          <b>{counts.total}</b><span>people</span>
          <b>+{counts.spaceWide}</b><span>space-wide</span>
        </div>
        <nav className="drw-tabs">
          {(['who', 'pages', 'why'] as const).map(t => (
            <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
              {t === 'who' ? 'Who can do what' : t === 'pages' ? `Pages (${under.length})` : 'Why it is here'}
            </button>
          ))}
        </nav>
      </div>

      <div className="drw-b">
        {tab === 'who' && (
          <>
            <p className="drw-note">
              {r.inherited
                ? <>Nothing is set on this folder. It takes its permissions from{' '}
                    {r.source
                      ? <a onClick={() => onSel({ t: 'folder', id: r.source })}><code>{r.source}</code></a>
                      : <b>the space root</b>}.
                  </>
                : <>Permissions are set <b>on this folder</b>, so everything below it inherits from here.</>}
            </p>
            <RoleTable d={d} edit={r.edit} publish={r.publish} structure={r.structure} read={r.read} />
            <PeopleList d={d} who={who} onSel={onSel} />
          </>
        )}

        {tab === 'pages' && (
          <>
            {here.length > 0 && <h4 className="drw-s">In this folder — {here.length}</h4>}
            {here.map(p => <PageRow key={p.current_url} p={p} onSel={onSel} />)}
            {under.length > here.length && (
              <>
                <h4 className="drw-s">In folders below — {under.length - here.length}</h4>
                {under.filter(p => p.folder !== path).slice(0, 300).map(p => (
                  <PageRow key={p.current_url} p={p} onSel={onSel} sub />
                ))}
                {under.length - here.length > 300 && (
                  <div className="more">First 300 shown — open the subfolder to see the rest.</div>
                )}
              </>
            )}
            {under.length === 0 && <p className="drw-note">No pages migrate into this folder.</p>}
          </>
        )}

        {tab === 'why' && (
          <dl className="drw-dl">
            <dt>New path</dt><dd><code>{path}</code></dd>
            <dt>Comes from</dt><dd><code>{f.source_web || '—'}</code></dd>
            <dt>Managed by</dt><dd>{f.managed_by || '—'}</dd>
            <dt>Confidence</dt><dd>{f.confidence || '—'}</dd>
            {f.countries && <><dt>Works in</dt><dd>{f.countries}</dd></>}
            {f.entity_basis && <><dt>Entity basis</dt><dd>{f.entity_basis}</dd></>}
            {f.also_belongs_to && <><dt>Also belongs to</dt><dd>{f.also_belongs_to}</dd></>}
            {f.event_owner && <><dt>Event owner</dt><dd>{f.event_owner}{f.last_ran ? ` · last ran ${f.last_ran}` : ''}</dd></>}
            {f.archive_candidate && <><dt>Archive?</dt><dd>{f.archive_candidate}</dd></>}
            {f.provenance && <><dt>Provenance</dt><dd>{f.provenance}</dd></>}
          </dl>
        )}
      </div>
    </>
  )
}

/* -------------------------------------------------------------------- page */

function PagePane({ d, url, onSel }: { d: Data; url: string; onSel: (s: Sel) => void }) {
  const p = d.pageByUrl.get(url)
  if (!p) return <div className="drw-b">Page not found.</div>
  const r = d.perm.rightsOf(p.folder)
  const who = d.perm.peopleOf(p.folder)
  const f = d.byPath.get(p.folder)

  return (
    <>
      <div className="drw-h">
        <div className="drw-crumb">
          <a onClick={() => onSel({ t: 'folder', id: p.folder })}><code>{p.folder}</code></a>
        </div>
        <h3>{leaf(p.new_path) || leaf(strip(p.current_url))}</h3>
        <div className="drw-tags">
          <span className={`ct ${p.content_type}`}>{p.content_type}</span>
          <span className={`chip ${p.action === 'Update and move' ? 'amber' : 'green'}`}>
            {p.action === 'Update and move' ? 'update, then move' : 'move as is'}
          </span>
          {p.moved_from && <span className="chip blue">moved to a hub</span>}
          {p.collision && <span className="chip amber">slug collision</span>}
        </div>
        <div className="drw-urls">
          <label>on aku.edu today</label>
          <a className="u old" href={p.current_url} target="_blank" rel="noreferrer">{strip(p.current_url)} ↗</a>
          <label>in Storyblok</label>
          <a className="u new" href={p.new_url} target="_blank" rel="noreferrer">{strip(p.new_url)} ↗</a>
        </div>
      </div>
      <div className="drw-b">
        <p className="drw-note">
          A page has no permissions of its own — it takes them from its folder,{' '}
          <a onClick={() => onSel({ t: 'folder', id: p.folder })}><code>{p.folder}</code></a>
          {r.inherited && r.source && <>, which in turn inherits from{' '}
            <a onClick={() => onSel({ t: 'folder', id: r.source })}><code>{r.source}</code></a></>}.
        </p>
        <h4 className="drw-s">What can be done to this page, and by whom</h4>
        <RoleTable d={d} edit={r.edit} publish={r.publish} structure={r.structure} read={r.read} page />
        <PeopleList d={d} who={who} onSel={onSel} page />
        <h4 className="drw-s">Where it sits</h4>
        <dl className="drw-dl">
          <dt>Region</dt><dd>{p.region || '—'}</dd>
          <dt>Entity</dt><dd>{p.entity || '—'}</dd>
          {p.department && <><dt>Department</dt><dd>{p.department}</dd></>}
          <dt>Managed by</dt><dd>{p.managed_by || f?.managed_by || '—'}</dd>
          {p.moved_from && <><dt>Moved from</dt><dd><code>{p.moved_from}</code></dd></>}
          {p.collision && <><dt>Collision</dt><dd>{p.collision}</dd></>}
          <dt>Confidence</dt><dd>{p.confidence || '—'}</dd>
        </dl>
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ person */

function PersonPane({ d, login, onSel }: { d: Data; login: string; onSel: (s: Sel) => void }) {
  const p = d.perm.byLogin.get(login)
  const [tab, setTab] = useState<'folders' | 'pages' | 'groups'>('folders')
  const reach = useMemo(() => (p ? d.perm.reachOf(p.login) : new Map()), [d, p])

  const rows = useMemo(
    () => [...reach.entries()]
      .map(([path, v]) => ({ path, ...v, pages: d.pagesUnder(path).length }))
      .sort((a, b) => a.path.localeCompare(b.path)),
    [reach, d],
  )
  const pages = useMemo(() => {
    const out: { page: (typeof d.livePages)[number]; capability: string }[] = []
    for (const pg of d.livePages) {
      const v = reach.get(pg.folder)
      if (v) out.push({ page: pg, capability: v.capability })
    }
    return out
  }, [reach, d])

  if (!p) return <div className="drw-b">Person not found.</div>

  const byCap: Record<string, number> = {}
  for (const v of reach.values()) byCap[v.capability] = (byCap[v.capability] || 0) + 1

  return (
    <>
      <div className="drw-h">
        <div className="drw-person">
          <span className={`av ${p.top_capability}`}>{initials(p.name)}</span>
          <div>
            <h3>{p.name}</h3>
            <span className="drw-mail">{p.email || p.login}</span>
          </div>
          <span className={`cap2 ${p.top_capability}`}>{p.top_capability}</span>
        </div>
        <div className="drw-tags">
          <span className="chip">{CAMPUS[p.campus] || p.campus}</span>
          {p.storyblok_roles.includes('space-admin') && (
            <span className="chip red">space admin — every folder</span>
          )}
        </div>
        <div className="drw-nums">
          <b>{reach.size}</b><span>folders</span>
          <b>{pages.length.toLocaleString()}</b><span>pages</span>
          <b>{p.grants.length}</b><span>direct grants</span>
          <b>{p.storyblok_roles.length}</b><span>roles</span>
        </div>
        <nav className="drw-tabs">
          {(['folders', 'pages', 'groups'] as const).map(t => (
            <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
              {t === 'folders' ? `Folders (${reach.size})`
                : t === 'pages' ? `Pages (${pages.length})` : 'Groups & roles'}
            </button>
          ))}
        </nav>
      </div>
      <div className="drw-b">
        {tab === 'folders' && (
          <>
            <p className="drw-note">
              {CAP_ORDER.filter(c => byCap[c]).map(c => `${byCap[c]} as ${c}`).join(', ')}.{' '}
              A <b>direct</b> grant is set on that folder in SharePoint; the rest cascade down from
              a folder above.
            </p>
            <table className="drw-t">
              <thead><tr><th>Folder</th><th>Can</th><th className="num">Pages</th></tr></thead>
              <tbody>
                {rows.slice(0, 400).map(r => (
                  <tr key={r.path} onClick={() => onSel({ t: 'folder', id: r.path })}>
                    <td><code>{r.path}</code></td>
                    <td>
                      <span className={`gcap ${r.capability}`}>{r.capability}</span>
                      {r.direct
                        ? <em className="dir">direct</em>
                        : r.where
                          ? <em className="inh" title={r.where}>via {leaf(r.where)}</em>
                          : <em className="inh">space-wide</em>}
                    </td>
                    <td className="num">{r.pages || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 400 && <div className="more">First 400 of {rows.length}.</div>}
          </>
        )}

        {tab === 'pages' && (
          <>
            <p className="drw-note">
              Every page this person can touch, and what they may do to it.
            </p>
            {pages.slice(0, 400).map(({ page, capability }) => (
              <div className="drw-pg" key={page.current_url} onClick={() => onSel({ t: 'page', id: page.current_url })}>
                <span className={`gcap ${capability}`}>{capability}</span>
                <code className="old">{strip(page.current_url)}</code>
                <span className="acts">{actionWords(capability)}</span>
              </div>
            ))}
            {pages.length > 400 && <div className="more">First 400 of {pages.length.toLocaleString()}.</div>}
            {pages.length === 0 && <p className="drw-note">No pages sit in the folders they hold.</p>}
          </>
        )}

        {tab === 'groups' && (
          <>
            <h4 className="drw-s">SharePoint groups today — {p.groups.length}</h4>
            <ul className="drw-ul">{p.groups.map(g => <li key={g}><code>{g}</code></li>)}</ul>
            <h4 className="drw-s">Storyblok roles to assign — {p.storyblok_roles.length}</h4>
            <ul className="drw-ul">
              {p.storyblok_roles.map(r => {
                const role = d.perm.roleByName.get(r)
                return (
                  <li key={r}>
                    <code>{r}</code>
                    {role && <em> · {role.capability} · {role.folders_scoped} folder{role.folders_scoped === 1 ? '' : 's'}</em>}
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </div>
    </>
  )
}

/* ----------------------------------------------------------------- pieces */

const actionWords = (cap: string) => {
  const c = CAN[cap] || CAN.viewer
  const out = ['read']
  if (c.create) out.push('create')
  if (c.edit) out.push('edit')
  if (c.publish) out.push('publish')
  if (c.del) out.push('delete')
  return out.join(' · ')
}

/** Which roles carry each action here, and how many named people hold them. A
 *  role nobody holds is called out — it is the difference between "the editor is
 *  someone else" and "nobody can edit this". */
function RoleTable({
  d, edit, publish, structure, read, page,
}: { d: Data; edit: string[]; publish: string[]; structure: string[]; read: string[]; page?: boolean }) {
  const thing = page ? 'this page' : 'pages in this folder'
  const ROWS: [string, string[]][] = [
    [`Create ${page ? 'a page beside it' : 'a page'}`, edit],
    [`Edit and save a draft of ${thing}`, edit],
    [`Publish ${thing}`, publish],
    [page ? 'Delete it, or move the folder' : 'Add, move or delete this folder', structure],
    [`Read ${thing}`, read],
  ]
  return (
    <table className="drw-t rt">
      <thead><tr><th>Action</th><th>Roles that carry it</th><th className="num">People</th></tr></thead>
      <tbody>
        {ROWS.map(([label, roles], i) => {
          const n = roles.reduce((a, r) => a + (d.perm.roleMembers.get(r)?.length || 0), 0)
          return (
            <tr key={i}>
              <td>{label}</td>
              <td>
                {roles.length === 0
                  ? <em className="none">nobody</em>
                  : roles.map(r => (
                    <code key={r} className={d.perm.roleMembers.has(r) ? 'role' : 'role empty'} title={
                      d.perm.roleMembers.has(r)
                        ? `${d.perm.roleMembers.get(r)!.length} people hold ${r}`
                        : `${r} is named by the folder but no person is in it yet`
                    }>{r}</code>
                  ))}
              </td>
              <td className={`num ${n ? '' : 'zero'}`}>{n || '—'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function PeopleList({
  d, who, onSel, page,
}: { d: Data; who: Who[]; onSel: (s: Sel) => void; page?: boolean }) {
  const [showAll, setShowAll] = useState(false)
  const [showSpace, setShowSpace] = useState(false)
  const own = who.filter(w => w.scope === 'folder')
  const space = who.filter(w => w.scope === 'space')
  const groups = CAP_ORDER.map(c => [c, own.filter(w => w.capability === c)] as const)
    .filter(([, list]) => list.length)

  return (
    <>
      <h4 className="drw-s">
        {own.length
          ? `${own.length} named people work on ${page ? 'this page' : 'this folder'}`
          : `Nobody is named on ${page ? 'this page' : 'this folder'}`}
      </h4>
      {own.length === 0 && (
        <p className="drw-note warn">
          No named person holds a folder-level permission here. Only the {space.length} space
          admins below can touch it — worth resolving before the migration, or this content has
          no owner.
        </p>
      )}
      {groups.map(([cap, list]) => (
        <div className="drw-cap" key={cap}>
          <div className="drw-caph">
            <span className={`gcap ${cap}`}>{CAP_LABEL[cap] || cap}</span>
            <i>{CAP_VERB[cap]}</i>
            <b>{list.length}</b>
          </div>
          {(showAll ? list : list.slice(0, 8)).map(w => (
            <div className="drw-who" key={w.person.login} onClick={() => onSel({ t: 'person', id: w.person.login })}>
              <span className={`av sm ${w.person.top_capability}`}>{initials(w.person.name)}</span>
              <b>{w.person.name}</b>
              <span className="drw-mail">{w.person.email}</span>
              {w.direct
                ? <em className="dir" title="the permission is set on this folder">direct</em>
                : w.where
                  ? <em className="inh" title={`inherited from ${w.where}`}>via {leaf(w.where)}</em>
                  : <em className="inh">space-wide</em>}
              <code className="via" title={w.via}>{w.via}</code>
            </div>
          ))}
          {!showAll && list.length > 8 && (
            <button className="lnk" onClick={() => setShowAll(true)}>
              show all {list.length}
            </button>
          )}
        </div>
      ))}

      {space.length > 0 && (
        <div className="drw-cap space">
          <div className="drw-caph">
            <span className="gcap admin">Space-wide</span>
            <i>{space.length} people reach every folder in the space, this one included</i>
            <button className="lnk" onClick={() => setShowSpace(!showSpace)}>
              {showSpace ? 'hide' : 'show'}
            </button>
          </div>
          {showSpace && space.map(w => (
            <div className="drw-who" key={w.person.login} onClick={() => onSel({ t: 'person', id: w.person.login })}>
              <span className={`av sm ${w.person.top_capability}`}>{initials(w.person.name)}</span>
              <b>{w.person.name}</b>
              <span className="drw-mail">{w.person.email}</span>
              <code className="via" title={w.via}>{w.via}</code>
            </div>
          ))}
        </div>
      )}

      <p className="drw-note sm">
        Counted from the {d.people.length} people the permissions export names. A role shown in
        grey is named by the folder but holds nobody yet — {d.perm.emptyRoles.size} of the{' '}
        {d.plan.roles.length} roles are in that state.
      </p>
    </>
  )
}

function PageRow({ p, onSel, sub }: { p: any; onSel: (s: Sel) => void; sub?: boolean }) {
  return (
    <div className={`drw-pg ${sub ? 'sub' : ''}`} onClick={() => onSel({ t: 'page', id: p.current_url })}>
      <span className={`pdot ${p.content_type}`} />
      <code className="old">{strip(p.current_url)}</code>
      <span className="to">→</span>
      <code className="new">{leaf(p.new_path)}</code>
      <a
        className="ext"
        href={p.current_url}
        target="_blank"
        rel="noreferrer"
        onClick={e => e.stopPropagation()}
        title="Open the live page on aku.edu"
      >↗</a>
    </div>
  )
}
