import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, Handle, Position, useReactFlow, ReactFlowProvider,
  type Edge, type Node, type NodeProps,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type { Data } from '../lib/store'
import { CAP_ORDER } from '../lib/perm'
import { KIND_LABEL, leaf } from '../lib/types'
import { downloadCsv } from '../lib/csv'
import { PersonPicker, Select, Toggle, type Sel } from '../lib/ui'
import Drawer from './Detail'

const BOX_W = 268
const GAP_X = 26
const GAP_Y = 152

const ICON: Record<string, string> = {
  region: '◉', entity: '■', department: '▪', centre: '◈', office: '◇',
  publication: '○', container: '▫', root: '⬢', division: '▸', section: '▹',
}

const PERMS = [
  { v: '', l: 'set or inherited' },
  { v: 'own', l: 'sets its own' },
  { v: 'inh', l: 'inherits' },
]

type Payload = {
  path: string
  name: string
  caption: string
  kind: string
  manager: string
  own: boolean
  source: string
  pages: number
  folders: number
  admins: number
  publishers: number
  editors: number
  people: number
  spaceWide: number
  childCount: number
  collapsed: boolean
  shared: string
  archive: string
  focusCap: string
  focusWhere: string
  dim: boolean
  selected: boolean
  onToggle: () => void
  onOpen: () => void
}

function FolderNode({ data }: NodeProps<Payload>) {
  const cls = [
    'fnode', `k-${data.kind}`,
    data.dim ? 'dim' : '',
    data.selected ? 'sel' : '',
    data.focusCap ? `foc f-${data.focusCap}` : '',
  ].filter(Boolean).join(' ')
  return (
    <div
      className={cls}
      onClick={data.onOpen}
      title={`${data.path}\n\n${data.people} people work on this folder, plus ${data.spaceWide} space admins.\nClick for the list.`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="fn-top">
        <div className="fn-ico">{ICON[data.kind] || '·'}</div>
        <div className="fn-txt">
          <b>{data.name}</b>
          <i>{data.caption}</i>
        </div>
        <div className="fn-right">
          {data.shared && <span className="fn-shared" title={data.shared}>shared</span>}
          {data.archive && <span className="fn-arch" title={data.archive}>archive?</span>}
          <span
            className={`fn-mgr ${data.own ? 'own' : 'inh'}`}
            title={data.own
              ? 'permissions are set on this folder'
              : data.source ? `inherits from ${data.source}` : 'inherits from the space root'}
          >{data.manager || '—'}</span>
        </div>
      </div>
      <div className="fn-bot">
        {data.focusCap
          ? (
            <span
              className={`gcap ${data.focusCap}`}
              title={data.focusWhere ? `granted via ${data.focusWhere}` : 'space-wide role'}
            >{data.focusCap}</span>
          )
          : (
            <span className={`fn-dot ${data.own ? 'own' : 'inh'}`}>
              {data.own ? 'sets rights' : 'inherits'}
            </span>
          )}
        <span className="fn-stat" title="pages below this folder">
          <em>{data.pages ? data.pages.toLocaleString() : '0'}</em> pages
        </span>
        <span className="fn-stat" title="folders below this one">
          <em>{data.folders || '0'}</em> sub
        </span>
        <span
          className="fn-ppl"
          title={`${data.admins} admins · ${data.publishers} publishers · ${data.editors} editors`}
        >
          {data.admins > 0 && <em className="adm">{data.admins}</em>}
          {data.publishers > 0 && <em className="pub">{data.publishers}</em>}
          {data.editors > 0 && <em className="edt">{data.editors}</em>}
          {data.people === 0 && <em className="non">nobody</em>}
        </span>
      </div>
      {data.childCount > 0 && (
        <button
          className="fn-tg"
          title={`${data.childCount} folders inside`}
          onClick={ev => { ev.stopPropagation(); data.onToggle() }}
        >
          {data.collapsed ? '+' : '−'}
        </button>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

const nodeTypes = { folder: FolderNode }

/** `fitView` as a prop only fires on first mount, and not reliably before the
 *  nodes have been measured. Refit whenever the node set changes so folding a
 *  branch never leaves you staring at empty canvas. */
function FitOnChange({ count }: { count: number }) {
  const rf = useReactFlow()
  useEffect(() => {
    // clamp the fit: fitting 600 boxes to the window makes every label unreadable,
    // so stop at a zoom you can still read and let the reader pan from there
    const t = setTimeout(
      () => rf.fitView({ padding: 0.2, duration: 240, minZoom: 0.5, maxZoom: 1 }),
      60,
    )
    return () => clearTimeout(t)
  }, [count, rf])
  return null
}

export default function OrgChart(props: { d: Data }) {
  return (
    <ReactFlowProvider>
      <Chart {...props} />
    </ReactFlowProvider>
  )
}

function Chart({ d }: { d: Data }) {
  const [q, setQ] = useState('')
  const [region, setRegion] = useState('')
  const [kind, setKind] = useState('')
  const [perm, setPerm] = useState('')
  const [cap, setCap] = useState('')
  const [hideEmpty, setHideEmpty] = useState(false)
  const [focus, setFocus] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [sel, setSel] = useState<Sel>(null)

  // Open the regions, fold everything below them, and fold staging whole: it is
  // not content, and left open it doubles the width and forces the zoom out.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    const s = new Set<string>()
    const walk = (p: string, depth: number) => {
      if (depth >= 1) s.add(p)
      for (const c of d.kids.get(p) || []) walk(c, depth + 1)
    }
    d.roots.forEach(r => (r === 'staging' ? s.add(r) : walk(r, 0)))
    return s
  })

  const toggle = useCallback((p: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(p) ? next.delete(p) : next.add(p)
      return next
    })
  }, [])

  const query = q.trim().toLowerCase()
  const reach = useMemo(() => (focus ? d.perm.reachOf(focus) : null), [focus, d])
  const person = focus ? d.perm.byLogin.get(focus) : null

  const folderOk = useCallback(
    (path: string) => {
      const f = d.byPath.get(path)!
      if (region && f.region !== region) return false
      if (kind && f.kind !== kind) return false
      if (perm === 'own' && f.own_permissions !== 'yes') return false
      if (perm === 'inh' && f.own_permissions === 'yes') return false
      if (hideEmpty && d.subPages(path) === 0) return false
      // scope 'folder' only — the 21 space admins are on every folder, so counting
      // them would make "has a named admin" select all 628
      if (cap && !d.perm.peopleOf(path).some(w => w.capability === cap && w.scope === 'folder'))
        return false
      if (reach && onlyMine && !reach.has(path)) return false
      if (query) {
        const hay = (f.new_path + ' ' + f.title + ' ' + f.managed_by + ' ' + f.kind).toLowerCase()
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
    [d, region, kind, perm, hideEmpty, cap, reach, onlyMine, query],
  )

  const filtering = !!(query || region || kind || perm || cap || hideEmpty || (reach && onlyMine))

  /** Everything that survives, plus its ancestors — a node whose parent is not
   *  drawn would float unattached. */
  const visible = useMemo(() => {
    if (!filtering) return null
    const keep = new Set<string>()
    for (const f of d.plan.folders) {
      if (!folderOk(f.new_path)) continue
      let cur = f.new_path
      for (;;) {
        keep.add(cur)
        if (!cur.includes('/')) break
        cur = cur.slice(0, cur.lastIndexOf('/'))
      }
    }
    return keep
  }, [filtering, d, folderOk])

  const matched = useMemo(
    () => d.plan.folders.filter(f => folderOk(f.new_path)).length,
    [d, folderOk],
  )

  /** Tidy tree layout: lay the leaves out left to right, then centre each parent
   *  over its children. Cheap, stable, and good enough for a folder tree. */
  const { nodes, edges } = useMemo(() => {
    const nodes: Node<Payload>[] = []
    const edges: Edge[] = []
    let cursor = 0

    const place = (path: string, depth: number): number => {
      const f = d.byPath.get(path)!
      // a filter overrides the fold: what survived it has to be on screen
      const isCollapsed = filtering ? false : collapsed.has(path)
      const all = (d.kids.get(path) || []).filter(c => !visible || visible.has(c))
      const kids = isCollapsed ? [] : all
      let x: number
      if (kids.length === 0) {
        x = cursor
        cursor += BOX_W + GAP_X
      } else {
        const xs = kids.map(c => place(c, depth + 1))
        x = (xs[0] + xs[xs.length - 1]) / 2
      }
      const r = d.perm.rightsOf(path)
      const c = d.perm.countsOf(path)
      const mine = reach?.get(path)
      const name = leaf(path)
      const title = (f.title || '').trim()
      nodes.push({
        id: path,
        type: 'folder',
        position: { x, y: depth * GAP_Y },
        data: {
          path,
          name,
          caption: title && title.toLowerCase() !== name.replace(/-/g, ' ')
            ? title : (KIND_LABEL[f.kind] || f.kind),
          kind: f.kind,
          manager: (f.managed_by || '').split(';')[0].trim(),
          own: f.own_permissions === 'yes',
          source: r.source,
          pages: d.subPages(path),
          folders: d.subFolders(path) - 1,
          admins: c.admin,
          publishers: c.publisher,
          editors: c.editor,
          people: c.total,
          spaceWide: c.spaceWide,
          childCount: all.length,
          collapsed: isCollapsed,
          shared: f.also_belongs_to || '',
          archive: f.archive_candidate || '',
          focusCap: mine ? mine.capability : '',
          focusWhere: mine?.where || '',
          dim: !!reach && !mine,
          selected: sel?.t === 'folder' && sel.id === path,
          onToggle: () => toggle(path),
          onOpen: () => setSel({ t: 'folder', id: path }),
        },
        draggable: true,
      })
      for (const c2 of kids) {
        edges.push({
          id: `${path}->${c2}`,
          source: path,
          target: c2,
          type: 'smoothstep',
          style: { strokeWidth: 1.5 },
        })
      }
      return x
    }

    for (const r of d.roots) {
      if (visible && !visible.has(r)) continue
      place(r, 0)
      cursor += BOX_W
    }
    return { nodes, edges }
  }, [d, collapsed, toggle, visible, filtering, reach, sel])

  const setDepth = (k: number) => {
    const next = new Set<string>()
    const walk = (p: string, depth: number) => {
      if (depth >= k) next.add(p)
      for (const c of d.kids.get(p) || []) walk(c, depth + 1)
    }
    d.roots.forEach(r => walk(r, 0))
    setCollapsed(next)
  }

  const reset = () => {
    setQ(''); setRegion(''); setKind(''); setPerm(''); setCap('')
    setHideEmpty(false); setFocus(''); setDepth(1)
  }

  const exportCsv = () => {
    const rows = nodes.map(n => {
      const p = n.data
      const f = d.byPath.get(p.path)!
      const r = d.perm.rightsOf(p.path)
      return [
        p.path, p.name, f.title, p.kind, f.region, f.entity,
        p.own ? 'sets its own' : 'inherits', r.source, f.managed_by,
        r.edit.join('; '), r.publish.join('; '), r.structure.join('; '),
        p.admins, p.publishers, p.editors, p.people, p.spaceWide, p.pages, p.folders, p.focusCap,
      ]
    })
    downloadCsv(
      'aku-org-chart.csv',
      ['new_path', 'name', 'title', 'kind', 'region', 'entity', 'permissions',
        'permission_source', 'managed_by', 'can_edit_roles', 'can_publish_roles',
        'can_delete_roles', 'admins', 'publishers', 'editors', 'people_total',
        'space_admins', 'pages_below', 'subfolders',
        person ? `${person.name}_can` : 'focus_person_can'],
      rows,
    )
  }

  return (
    <section className="chart-screen">
      <h2>Org chart</h2>
      <p className="lede">
        The folder tree drawn top to bottom, with the people who can work in each folder.{' '}
        <b>Click a box</b> for who can create, edit, publish or delete there, and every page it
        holds. <b>Drag to pan, scroll to zoom</b>; <b>−</b> / <b>+</b> folds a branch. Showing{' '}
        <b>{nodes.length}</b> of {d.plan.folders.length} folders.
      </p>

      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a folder, team or person…"
        />
        <Select label="Region" value={region} onChange={setRegion}
          options={[{ v: '', l: 'all regions' }, ...d.regions.map(r => ({ v: r, l: r }))]} />
        <Select label="Kind" value={kind} onChange={setKind}
          options={[{ v: '', l: 'all kinds' }, ...d.kinds.map(k => ({ v: k, l: KIND_LABEL[k] || k }))]} />
        <Select label="Permissions" value={perm} onChange={setPerm} options={PERMS} />
        <Select label="Has" value={cap} onChange={setCap}
          options={[{ v: '', l: 'anyone' }, ...CAP_ORDER.map(c => ({ v: c, l: `a named ${c}` }))]} />
        <Toggle on={hideEmpty} onChange={setHideEmpty}>Only folders with pages</Toggle>
      </div>

      <div className="bar">
        <PersonPicker people={d.people} value={focus} onPick={setFocus} />
        {focus && <Toggle on={onlyMine} onChange={setOnlyMine}>Only their folders</Toggle>}
        <span className="hits">
          {filtering ? `${matched} folders match` : `${d.plan.folders.length} folders`}
        </span>
        <button className="btn" onClick={() => setDepth(1)}>Regions</button>
        <button className="btn" onClick={() => setDepth(3)}>Entities</button>
        <button className="btn" onClick={() => setDepth(4)}>Departments</button>
        <button className="btn" onClick={() => setCollapsed(new Set())}>Open everything</button>
        <button className="btn" onClick={reset}>Reset</button>
        <button className="btn go" onClick={exportCsv}>Download CSV</button>
      </div>

      {focus && person && (
        <p className="note g">
          Focused on <b>{person.name}</b> — the badge on each box is what they may do there, and
          folders they cannot touch are faded. {reach!.size} folders,{' '}
          {d.livePages.filter(p => reach!.has(p.folder)).length.toLocaleString()} pages.{' '}
          <a onClick={() => setSel({ t: 'person', id: focus })}>Open their full access →</a>
        </p>
      )}

      <div className="oclegend">
        <span><i className="sw adm" /> admins</span>
        <span><i className="sw pub" /> publishers</span>
        <span><i className="sw edt" /> editors</span>
        <span><i className="sw non" /> nobody named</span>
        <i className="sep" />
        <span><i className="sw k-region" /> region</span>
        <span><i className="sw k-entity" /> entity</span>
        <span><i className="sw k-department" /> department</span>
        <span><i className="sw k-centre" /> centre</span>
        <i className="sep" />
        <span><b>sets rights</b> permissions start here</span>
        <span><b>inherits</b> comes from a folder above</span>
      </div>

      <div className="flowwrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
        >
          <FitOnChange count={nodes.length} />
          <Background gap={22} size={1} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeStrokeWidth={2} />
        </ReactFlow>
      </div>

      <Drawer d={d} sel={sel} onSel={setSel} />
    </section>
  )
}
