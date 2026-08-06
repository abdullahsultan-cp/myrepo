import { useCallback, useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { KIND_LABEL, leaf, strip } from '../lib/types'
import { CAP_ORDER } from '../lib/perm'
import { downloadCsv } from '../lib/csv'
import { PersonPicker, Select, Toggle, type Sel } from '../lib/ui'
import Drawer from './Detail'

type Props = { d: Data }

const ACTIONS = [
  { v: '', l: 'any action' },
  { v: 'Move as is', l: 'move as is' },
  { v: 'Update and move', l: 'update first' },
]
const TYPES = [
  { v: '', l: 'any type' },
  { v: 'page', l: 'pages' },
  { v: 'news', l: 'news' },
  { v: 'event', l: 'events' },
  { v: 'blog', l: 'blogs' },
]
const PERMS = [
  { v: '', l: 'set or inherited' },
  { v: 'own', l: 'sets its own' },
  { v: 'inh', l: 'inherits' },
]

export default function FolderTree({ d }: Props) {
  const [q, setQ] = useState('')
  const [region, setRegion] = useState('')
  const [kind, setKind] = useState('')
  const [perm, setPerm] = useState('')
  const [action, setAction] = useState('')
  const [type, setType] = useState('')
  const [cap, setCap] = useState('')
  const [hideEmpty, setHideEmpty] = useState(false)
  const [focus, setFocus] = useState('')
  const [onlyMine, setOnlyMine] = useState(true)
  const [sel, setSel] = useState<Sel>(null)
  const [open, setOpen] = useState<Set<string>>(new Set(d.roots))

  const query = q.trim().toLowerCase()
  const reach = useMemo(() => (focus ? d.perm.reachOf(focus) : null), [focus, d])
  const person = focus ? d.perm.byLogin.get(focus) : null

  /** A page survives the page-level filters. Folder filters are separate: a folder
   *  can match while none of its pages do, and both have to be visible. */
  const pageOk = useCallback(
    (p: (typeof d.livePages)[number]) => {
      if (action && p.action !== action) return false
      if (type && p.content_type !== type) return false
      if (query && !(p.new_path + ' ' + p.current_url + ' ' + p.managed_by).toLowerCase().includes(query))
        return false
      return true
    },
    [action, type, query],
  )

  const folderOk = useCallback(
    (path: string) => {
      const f = d.byPath.get(path)!
      if (region && f.region !== region) return false
      if (kind && f.kind !== kind) return false
      if (perm === 'own' && f.own_permissions !== 'yes') return false
      if (perm === 'inh' && f.own_permissions === 'yes') return false
      // scope 'folder' only: every folder has the 21 space admins, so counting
      // them would make "has a named admin" select all 628
      if (cap && !d.perm.peopleOf(path).some(w => w.capability === cap && w.scope === 'folder'))
        return false
      if (reach && onlyMine && !reach.has(path)) return false
      if (query) {
        const hay = (f.new_path + ' ' + f.title + ' ' + f.managed_by + ' ' + f.kind + ' ' +
          f.can_create_and_edit + ' ' + f.can_publish).toLowerCase()
        // folder-scoped only: a space admin is on all 628, so searching their
        // name would "match" every folder and tell you nothing
        const peopleHit = d.perm.peopleOf(path).some(
          w => w.scope === 'folder' &&
            (w.person.name + ' ' + w.person.email).toLowerCase().includes(query),
        )
        if (!hay.includes(query) && !peopleHit) return false
      }
      return true
    },
    [d, region, kind, perm, cap, reach, onlyMine, query],
  )

  const filtering = !!(query || region || kind || perm || cap || action || type || (reach && onlyMine))

  /** Folders that survive, plus every ancestor, so a hit deep in the tree is
   *  reachable rather than orphaned. */
  const visible = useMemo(() => {
    if (!filtering) return null
    const keep = new Set<string>()
    const addUp = (p: string) => {
      let cur = p
      for (;;) {
        keep.add(cur)
        if (!cur.includes('/')) break
        cur = cur.slice(0, cur.lastIndexOf('/'))
      }
    }
    for (const f of d.plan.folders) if (folderOk(f.new_path)) addUp(f.new_path)
    // a folder holding a matching page stays, even if the folder itself does not match
    if (query || action || type) {
      for (const p of d.livePages) if (pageOk(p)) addUp(p.folder)
    }
    return keep
  }, [filtering, d, folderOk, pageOk, query, action, type])

  const matched = useMemo(
    () => (visible ? d.plan.folders.filter(f => folderOk(f.new_path)).length : d.plan.folders.length),
    [visible, d, folderOk],
  )

  const toggle = (p: string) =>
    setOpen(prev => {
      const next = new Set(prev)
      next.has(p) ? next.delete(p) : next.add(p)
      return next
    })

  const setDepth = (k: number) => {
    const next = new Set<string>()
    const walk = (p: string, depth: number) => {
      if (depth < k) next.add(p)
      for (const c of d.kids.get(p) || []) walk(c, depth + 1)
    }
    d.roots.forEach(r => walk(r, 0))
    setOpen(next)
  }
  const openAll = () => setOpen(new Set(d.plan.folders.map(f => f.new_path)))

  const reset = () => {
    setQ(''); setRegion(''); setKind(''); setPerm(''); setAction(''); setType('')
    setCap(''); setHideEmpty(false); setFocus(''); setOpen(new Set(d.roots))
  }

  const exportCsv = () => {
    const rows = d.plan.folders
      .filter(f => folderOk(f.new_path))
      .map(f => {
        const r = d.perm.rightsOf(f.new_path)
        const c = d.perm.countsOf(f.new_path)
        const mine = reach?.get(f.new_path)
        const named = (cap: string) => d.perm.peopleOf(f.new_path)
          .filter(w => w.scope === 'folder' && w.capability === cap)
          .map(w => w.person.name).join('; ')
        return [
          f.new_path, f.title, f.kind, f.region, f.entity, f.source_web,
          d.pagesByFolder.get(f.new_path)?.length || 0, d.pagesUnder(f.new_path).length,
          f.own_permissions === 'yes' ? 'sets its own' : 'inherits', r.source,
          f.managed_by, r.edit.join('; '), r.publish.join('; '), r.structure.join('; '),
          c.admin, c.publisher, c.editor, c.total, c.spaceWide,
          named('publisher'), named('editor'),
          mine ? mine.capability : '', f.confidence,
        ]
      })
    downloadCsv(
      'aku-folders-and-who-can-edit.csv',
      ['new_path', 'title', 'kind', 'region', 'entity', 'source_web', 'pages_here',
        'pages_below', 'permissions', 'permission_source', 'managed_by', 'can_edit_roles',
        'can_publish_roles', 'can_delete_roles', 'admins', 'publishers', 'editors',
        'people_total', 'space_admins', 'publisher_names', 'editor_names',
        person ? `${person.name}_can` : 'focus_person_can', 'confidence'],
      rows,
    )
  }

  const Node = ({ path, depth }: { path: string; depth: number }) => {
    const f = d.byPath.get(path)!
    if (visible && !visible.has(path)) return null
    const pages = (d.pagesByFolder.get(path) || []).filter(pageOk)
    const tp = d.subPages(path)
    if (hideEmpty && tp === 0) return null
    const kids = d.kids.get(path) || []
    // while a filter is on, everything that survived it is shown open — a hit five
    // levels down that you still have to click open is not a hit you can see
    const isOpen = filtering ? true : open.has(path)
    const has = kids.length > 0 || pages.length > 0
    const name = leaf(path)
    const title = (f.title || '').trim()
    const showTitle = title && title.toLowerCase() !== name.replace(/-/g, ' ')
    const tf = d.subFolders(path) - 1
    const r = d.perm.rightsOf(path)
    const c = d.perm.countsOf(path)
    const mine = reach?.get(path)

    return (
      <div className="n">
        <div className={`row k-${f.kind} ${sel?.t === 'folder' && sel.id === path ? 'sel' : ''}`}
          onClick={() => has && toggle(path)} title={path}>
          <span className={`tw ${has ? (isOpen ? 'o' : '') : 'leaf'}`} />
          <span className="nm">{name}</span>
          {showTitle && <span className="ttl">{title}</span>}
          <span className="ty">{KIND_LABEL[f.kind] || f.kind}</span>

          {mine && (
            <span className={`gcap ${mine.capability}`} title={
              mine.direct ? 'granted on this folder' : mine.where ? `inherited from ${mine.where}` : 'space-wide'
            }>{mine.capability}</span>
          )}
          {f.also_belongs_to && <span className="chip blue" title={f.also_belongs_to}>shared</span>}
          {f.event_owner && (
            <span className="chip blue" title={`Run by ${f.event_owner}`}>
              {f.last_ran ? `ran ${f.last_ran}` : 'event'}
            </span>
          )}
          {f.archive_candidate && <span className="chip amber" title={f.archive_candidate}>archive?</span>}
          {f.own_permissions === 'yes' && (
            <span className="chip green" title={`Permissions are set on this folder.
Can create and edit: ${r.edit.join(', ') || '—'}
Can publish: ${r.publish.join(', ') || '—'}`}>sets permissions</span>
          )}

          <span className="meta">
            {tf ? `${tf} folder${tf === 1 ? '' : 's'}` : ''}
            {tf && tp ? ' · ' : ''}
            {tp ? `${tp.toLocaleString()} page${tp === 1 ? '' : 's'}` : tf ? '' : 'empty'}
          </span>

          <button
            className="who"
            title={`${c.total} people work on this folder — ${c.publisher} publishers, ${c.editor} editors, ${c.admin} admins.
Plus ${c.spaceWide} space admins, who reach every folder.
Click for the full list.`}
            onClick={ev => { ev.stopPropagation(); setSel({ t: 'folder', id: path }) }}
          >
            <span className="wi">👤</span>
            {c.publisher > 0 && <em className="pub">{c.publisher}</em>}
            {c.editor > 0 && <em className="edt">{c.editor}</em>}
            {c.total === 0 && <em className="non">none</em>}
          </button>
          <span className={`team ${f.own_permissions === 'yes' ? 'own' : 'inh'}`}
            title={r.inherited && r.source ? `inherits from ${r.source}` : 'set here'}>
            {f.own_permissions === 'yes' ? f.managed_by : `inherits · ${(f.managed_by || '').split(';')[0].trim()}`}
          </span>
        </div>

        {isOpen && has && (
          <div className="ch">
            {kids.map(c2 => <Node key={c2} path={c2} depth={depth + 1} />)}
            {pages.length > 0 && (
              <div className="pgs">
                {pages.map(p => (
                  <div
                    className={`pg ${sel?.t === 'page' && sel.id === p.current_url ? 'sel' : ''}`}
                    key={p.current_url}
                    onClick={() => setSel({ t: 'page', id: p.current_url })}
                    title="Open this page — who can edit, publish or delete it"
                  >
                    <span className={`pdot ${p.content_type}`} />
                    <span className="pn">{leaf(p.new_path)}</span>
                    <a
                      className="slug old"
                      href={p.current_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={e => e.stopPropagation()}
                      title={`Open the live page: ${p.current_url}`}
                    >{strip(p.current_url)} ↗</a>
                    <span className="to">→</span>
                    <a
                      className="slug new"
                      href={p.new_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={e => e.stopPropagation()}
                      title={`New location: ${p.new_url}`}
                    >{strip(p.new_url)}</a>
                    <span className={`pact ${p.action === 'Update and move' ? 'u' : ''}`}>
                      {p.action === 'Update and move' ? 'update first' : 'move as is'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <section>
      <h2>Folder structure</h2>
      <p className="lede">
        Click a row to open it, the <b>👤 badge</b> to see everyone who can work in that folder, and
        any <b>page</b> to see who may edit, publish or delete it. The grey slug links to the live
        page on aku.edu. Children are listed in the order AKU&rsquo;s own menus use — about,
        programmes, research, faculty, departments, then news, events and blogs, then A–Z.
      </p>

      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={ev => setQ(ev.target.value)}
          placeholder="Search a folder, page, team, role or person…"
        />
        <Select label="Region" value={region} onChange={setRegion}
          options={[{ v: '', l: 'all regions' }, ...d.regions.map(r => ({ v: r, l: r }))]} />
        <Select label="Kind" value={kind} onChange={setKind}
          options={[{ v: '', l: 'all kinds' }, ...d.kinds.map(k => ({ v: k, l: KIND_LABEL[k] || k }))]} />
        <Select label="Permissions" value={perm} onChange={setPerm} options={PERMS} />
        <Select label="Has" value={cap} onChange={setCap}
          options={[{ v: '', l: 'anyone' }, ...CAP_ORDER.map(c => ({ v: c, l: `a named ${c}` }))]} />
        <Select label="Action" value={action} onChange={setAction} options={ACTIONS} />
        <Select label="Type" value={type} onChange={setType} options={TYPES} />
      </div>

      <div className="bar">
        <PersonPicker people={d.people} value={focus} onPick={setFocus} />
        {focus && (
          <Toggle on={onlyMine} onChange={setOnlyMine}>
            Only folders they can touch
          </Toggle>
        )}
        <Toggle on={hideEmpty} onChange={setHideEmpty}>Hide empty folders</Toggle>
        <span className="hits">
          {filtering
            ? `${matched.toLocaleString()} of ${d.plan.folders.length} folders match`
            : `${d.plan.folders.length} folders`}
        </span>
        <button className="btn" onClick={() => setDepth(1)}>Regions</button>
        <button className="btn" onClick={() => setDepth(3)}>Entities</button>
        <button className="btn" onClick={() => setDepth(4)}>Departments</button>
        <button className="btn" onClick={openAll}>Open everything</button>
        <button className="btn" onClick={reset}>Reset</button>
        <button className="btn go" onClick={exportCsv}>Download CSV</button>
      </div>

      {focus && person && (
        <p className="note g">
          Focused on <b>{person.name}</b> — {reach!.size} folders,{' '}
          {d.livePages.filter(p => reach!.has(p.folder)).length.toLocaleString()} pages.
          The badge on each row is what they may do there.{' '}
          <a onClick={() => setSel({ t: 'person', id: focus })}>Open their full access →</a>
        </p>
      )}

      <div id="tree">
        {d.roots.map(r => <Node key={r} path={r} depth={0} />)}
      </div>

      <Drawer d={d} sel={sel} onSel={setSel} />
    </section>
  )
}
