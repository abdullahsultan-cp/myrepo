/** The 345 custom roles, as the tree they actually form.
 *
 *  Shown as a tree rather than a list because the only thing worth knowing about
 *  a role is what sits above it: whoever holds the parent already covers this
 *  scope, so the parent is always the shorter grant to give. A flat table hides
 *  exactly that.
 *
 *  Filter by rung to see one ladder at a time -- the contributor tree and the
 *  approver tree are separate trees, and reading them together is what makes 345
 *  look unmanageable.
 */
import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import type { CustomRole } from '../lib/types'
import { TIER_LABEL } from '../lib/types'

export default function Hierarchy({ d }: { d: Data }) {
  const { rd, roleById, roleKids } = d
  const [q, setQ] = useState('')
  const [rung, setRung] = useState('approver')
  const [shut, setShut] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState<string>('')

  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of rd.roles) m[r.capability] = (m[r.capability] || 0) + 1
    return m
  }, [rd])

  const t = q.trim().toLowerCase()
  const hit = (r: CustomRole) =>
    !t ||
    (r.role + ' ' + r.unit + ' ' + r.scope_path + ' ' + r.replaces_groups)
      .toLowerCase()
      .includes(t)

  // A search has to keep a role's ancestors, or a match five levels down appears
  // with nothing above it and reads as a top-level role.
  const keep = useMemo(() => {
    if (!t) return null
    const k = new Set<string>()
    for (const r of rd.roles) {
      if (!hit(r)) continue
      let cur: CustomRole | undefined = r
      while (cur) {
        if (k.has(cur.role)) break
        k.add(cur.role)
        cur = cur.parent_role ? roleById.get(cur.parent_role) : undefined
      }
    }
    return k
  }, [rd, t, roleById])

  const inRung = (r: CustomRole) => rung === 'all' || r.capability === rung
  const roots = rd.roles
    .filter(r => inRung(r) && !r.parent_role && r.tier !== 'functional')
    .map(r => r.role)
    .sort()
  const funcs = rd.roles.filter(r => r.tier === 'functional')

  const shown = rd.roles.filter(r => inRung(r) && (!keep || keep.has(r.role)))

  function Node({ id, depth }: { id: string; depth: number }) {
    const r = roleById.get(id)
    if (!r) return null
    if (keep && !keep.has(id)) return null
    if (!inRung(r)) return null
    const kids = (roleKids.get(id) || []).filter(k => {
      const kr = roleById.get(k)
      return kr && inRung(kr) && (!keep || keep.has(k))
    })
    const closed = shut.has(id) && !keep
    const isOpen = open === id
    return (
      <div className="rn">
        <div
          className={`rrow ${isOpen ? 'sel' : ''}`}
          style={{ paddingLeft: 10 + depth * 19 }}
          onClick={() => setOpen(isOpen ? '' : id)}
        >
          <span
            className={`rtw ${kids.length ? (closed ? 'cl' : '') : 'leaf'}`}
            onClick={e => {
              e.stopPropagation()
              if (!kids.length) return
              const s = new Set(shut)
              if (s.has(id)) s.delete(id)
              else s.add(id)
              setShut(s)
            }}
          />
          <span className={`tpill ${r.tier}`}>{TIER_LABEL[r.tier]}</span>
          <code className="rid">{r.role}</code>
          {r.provenance === 'designed' ? (
            <span className="warn" title={r.note}>
              vacant
            </span>
          ) : null}
          <span className="rmeta">
            {r.members ? `${r.members} ${r.members === 1 ? 'person' : 'people'}` : '—'}
            <i> · </i>
            {r.scope_folders} folders
          </span>
          <span className="runit">{r.unit === '(vacant)' ? '' : r.unit}</span>
        </div>
        {isOpen && (
          <div className="rdet" style={{ marginLeft: 10 + depth * 19 }}>
            <div>
              <h5>Scope</h5>
              <code>{r.scope_path}</code>
              <p>
                Covers <b>{r.scope_folders}</b> folders — this one and everything under
                it.
              </p>
            </div>
            <div>
              <h5>Already covered by</h5>
              {r.parent_role ? (
                <>
                  <code>{r.parent_role}</code>
                  <p>
                    Anyone in that role can do this here too. Grant it instead when the
                    person really does run the wider area.
                  </p>
                </>
              ) : (
                <p className="dim">Nothing — this is the top of its ladder.</p>
              )}
            </div>
            <div>
              <h5>Replaces</h5>
              {r.replaces_groups ? (
                <>
                  <code className="sm">{r.replaces_groups}</code>
                  <p className="sm dim">{r.old_role_strings}</p>
                </>
              ) : (
                <p className="dim">
                  {r.note || 'No SharePoint group — this rung is new.'}
                </p>
              )}
            </div>
          </div>
        )}
        {!closed && kids.map(k => <Node key={k} id={k} depth={depth + 1} />)}
      </div>
    )
  }

  return (
    <section>
      <h2>The role hierarchy</h2>
      <p className="lede">
        {rd.roles.length} roles. Indentation is inheritance: whoever holds a role{' '}
        <b>also covers everything indented under it</b>. Click a role for its scope and
        what it replaces; click the arrow to fold. <b>vacant</b> marks a rung the export
        does not witness — the tier exists so the level below can be delegated, and AKU
        decides who holds it.
      </p>

      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a role, team or SharePoint group — try Anaesthesiology…"
        />
        <span className="hits">
          {shown.length} of {rd.roles.length} roles
        </span>
      </div>
      <div className="bar">
        {['all', ...rd.ladder].map(c => (
          <button
            key={c}
            className={`btn ${rung === c ? 'on' : ''}`}
            onClick={() => setRung(c)}
          >
            {c === 'all' ? 'Every rung' : c}
            {c !== 'all' && <b className="bc">{counts[c] || 0}</b>}
          </button>
        ))}
      </div>
      {rung !== 'all' && (
        <div className="note g">
          Showing the <b>{rung}</b> ladder on its own. Each rung is its own tree —
          reading them stacked together is what makes {rd.roles.length} roles look
          unmanageable when a person needs one or two.
        </div>
      )}

      <div id="rtree">
        {roots.map(r => (
          <Node key={r} id={r} depth={0} />
        ))}
        {rung === 'all' && funcs.length > 0 && (
          <>
            <div className="rsep">Not folder-scoped</div>
            {funcs
              .filter(r => !keep || keep.has(r.role))
              .map(r => (
                <div className="rrow" key={r.role} style={{ paddingLeft: 10 }}>
                  <span className="rtw leaf" />
                  <span className="tpill functional">fn</span>
                  <code className="rid">{r.role}</code>
                  <span className="rmeta">{r.members || '—'} people</span>
                  <span className="runit sm dim">{r.means}</span>
                </div>
              ))}
          </>
        )}
      </div>
    </section>
  )
}
