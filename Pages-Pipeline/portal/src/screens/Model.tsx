/** The permission model on one screen: the two axes, the ladder, and the
 *  translation from every SharePoint role string AKU uses today.
 *
 *  Ordered so it answers questions in the order they get asked. What are the
 *  rungs. What does each rung let someone do. How far does a rung reach. What
 *  happens to what we have today. The old-site tables come last because they are
 *  the check, not the explanation.
 */
import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { TIER_LABEL, TIER_REACH } from '../lib/types'

const CELL: Record<string, { t: string; c: string; title: string }> = {
  y: { t: '✓', c: 'y', title: 'yes, anywhere in the space' },
  s: { t: '✓', c: 's', title: 'yes, but only inside the folders this role is scoped to' },
  '-': { t: '—', c: 'n', title: 'no' },
}

export default function Model({ d }: { d: Data }) {
  const { rd } = d
  const [q, setQ] = useState('')

  const byTier = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of rd.roles) m[r.tier] = (m[r.tier] || 0) + 1
    return m
  }, [rd])

  const strings = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return rd.old_strings
    return rd.old_strings.filter(s =>
      (s.old_role_string + ' ' + s.new_capability + ' ' + s.plus_functional_role)
        .toLowerCase()
        .includes(t),
    )
  }, [rd, q])

  const totalRows = rd.old_strings.reduce((n, s) => n + s.permission_rows, 0)
  const deadRows = rd.old_strings
    .filter(s => s.new_capability === '(none)')
    .reduce((n, s) => n + s.permission_rows, 0)

  return (
    <section>
      <h2>How permissions work</h2>
      <p className="lede">
        A role is <b>one rung of a ladder, at one place in the tree</b> — nothing else.
        That is the whole model: pick what someone may do, pick where, and the role
        name writes itself. <code>pakistan.medical-college.anaesthesiology.approver</code>{' '}
        is the approver rung, anchored on Anaesthesiology.
      </p>

      {/* ---- axis 1: the ladder ---- */}
      <h3>Axis 1 · what a role may do</h3>
      <p className="lede">
        Five rungs, and each one contains the one below it — so nobody ever needs two
        content roles on the same folder. An approver can already do everything a
        contributor can.
      </p>
      <div className="ladder">
        {rd.ladder.map((cap, i) => (
          <div className={`rung ${cap}`} key={cap}>
            <span className="lv">{i}</span>
            <div>
              <b>{cap}</b>
              <span>{rd.means[cap]}</span>
            </div>
          </div>
        ))}
      </div>

      <h3>Axis 2 · how far it reaches</h3>
      <p className="lede">
        Scope runs <b>downward</b>. A role anchored on a faculty covers every department
        and section inside it, which is what makes one grant enough. The tier is just
        how deep the anchor sits.
      </p>
      <div className="tierbars">
        {rd.tiers.map((t, i) => (
          <div className="tb" key={t} style={{ marginLeft: i * 20 }}>
            <span className="tbn">{TIER_LABEL[t]}</span>
            <span className="tbr">{TIER_REACH[t]}</span>
            <span className="tbc">{byTier[t] || 0} roles</span>
          </div>
        ))}
        <div className="tb fn">
          <span className="tbn">{TIER_LABEL.functional}</span>
          <span className="tbr">{TIER_REACH.functional}</span>
          <span className="tbc">{byTier.functional || 0} roles</span>
        </div>
      </div>

      {/* ---- the matrix ---- */}
      <h3>What each rung may do</h3>
      <p className="lede">
        <span className="key y">✓</span> anywhere &nbsp;
        <span className="key s">✓</span> only inside its own scope &nbsp;
        <span className="key n">—</span> no. Hover any cell.
      </p>
      <div className="tw2">
        <table className="mx">
          <thead>
            <tr>
              <th>Action</th>
              {rd.ladder.map(c => (
                <th key={c} className="mxh">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rd.matrix.map(row => (
              <tr key={row.action}>
                <td>{row.action}</td>
                {rd.ladder.map(c => {
                  const v = CELL[row[c]] || CELL['-']
                  return (
                    <td key={c} className={`yn ${v.c}`} title={v.title}>
                      {v.t}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>The five roles that are not about folders</h3>
      <p className="lede">
        These govern a shared resource, so a folder scope would mean nothing. They are
        held separately from the ladder.
      </p>
      <table>
        <thead>
          <tr>
            <th>Role</th>
            <th>Governs</th>
            <th>People today</th>
            <th>From</th>
          </tr>
        </thead>
        <tbody>
          {rd.roles
            .filter(r => r.tier === 'functional')
            .map(r => (
              <tr key={r.role}>
                <td>
                  <code>
                    <b>{r.role}</b>
                  </code>
                </td>
                <td>{r.means}</td>
                <td className="num">{r.members || '—'}</td>
                <td className="sm">
                  {r.replaces_groups ? (
                    <code className="sm">{r.replaces_groups}</code>
                  ) : (
                    <span className="dim">new — nobody holds this today</span>
                  )}
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      {/* ---- the translation ---- */}
      <h3>Every permission AKU uses today, and what it becomes</h3>
      <p className="lede">
        All {rd.old_strings.length} distinct <code>Assigned Roles</code> values in the
        export, covering {totalRows.toLocaleString()} permission rows. Two of them
        deliberately translate to nothing — read the note before treating that as a
        loss.
      </p>
      <div className="note">
        <b>{deadRows.toLocaleString()} rows grant nothing and are not carried over.</b>{' '}
        <code>Limited Access</code> is plumbing SharePoint adds so someone can traverse
        to an item they were granted directly; it is not access to anything.{' '}
        <code>Design</code> ships with <code>Contribute</code> by default on a publishing
        site, so treating it as a grant would tell AKU that hundreds of content people
        may rewrite component schemas. Only the <code>Designers</code> group becomes{' '}
        <code>component-developer</code>.
      </div>
      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a SharePoint role string — try Approve…"
        />
        <span className="hits">
          {strings.length} of {rd.old_strings.length} role strings
        </span>
      </div>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>SharePoint says</th>
              <th className="num">Rows</th>
              <th>Becomes</th>
              <th>Plus</th>
              <th>Which means</th>
            </tr>
          </thead>
          <tbody>
            {strings.map(s => (
              <tr key={s.old_role_string}>
                <td>
                  <code className="sm">{s.old_role_string}</code>
                </td>
                <td className="num">{s.permission_rows.toLocaleString()}</td>
                <td className={`cap2c ${s.new_capability}`}>
                  {s.new_capability === '(none)' ? (
                    <span className="dim">nothing</span>
                  ) : (
                    <b>{s.new_capability}</b>
                  )}
                </td>
                <td className="sm">
                  {s.plus_functional_role ? <code>{s.plus_functional_role}</code> : ''}
                </td>
                <td className="sm dim">{s.note || s.means}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
