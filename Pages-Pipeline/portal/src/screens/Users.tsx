/** Every person on aku.edu: what they hold today, beside what to give them.
 *
 *  Two columns side by side, because that is the only form in which the answer is
 *  checkable. Pick a name, read the SharePoint groups on the left, read the
 *  custom roles on the right, and decide whether the right-hand side is correct.
 *  A summary of how the mapping was derived cannot be checked that way.
 *
 *  Sorted widest-access first, since those are the rows worth a human's attention
 *  -- 440 of the 584 need exactly one role.
 */
import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { CAMPUS, TIER_LABEL } from '../lib/types'

const initials = (n: string) =>
  n
    .split(/\s+/)
    .slice(0, 2)
    .map(w => w[0])
    .join('')
    .toUpperCase() || '?'

export default function Users({ d }: { d: Data }) {
  const { rd, roleById } = d
  const [q, setQ] = useState('')
  const [cap, setCap] = useState('')
  const [only, setOnly] = useState(false)
  const [who, setWho] = useState('')

  const U = rd.users
  const byCap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const u of U) m[u.top_capability] = (m[u.top_capability] || 0) + 1
    return m
  }, [U])

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return U.filter(u => {
      if (cap && u.top_capability !== cap) return false
      if (only && !u.simplify_to) return false
      if (!t) return true
      return (u.name + ' ' + u.email + ' ' + u.new_roles + ' ' + u.old_groups)
        .toLowerCase()
        .includes(t)
    })
  }, [U, q, cap, only])

  const wide = U.filter(u => u.new_role_count > 3).length
  const simplifiable = U.filter(u => u.simplify_to).length
  const grants = U.reduce((n, u) => n + u.folders_before_collapse, 0)
  const assigns = U.reduce((n, u) => n + u.new_role_count, 0)

  return (
    <section>
      <h2>People, and the roles to give them</h2>
      <p className="lede">
        {U.length} named people hold a permission on aku.edu today. The left of every
        row is what SharePoint says; the right is what to create in Storyblok. Click a
        row to see both in full.
      </p>

      <div className="tiles">
        <div className="tile hl">
          <b>{grants.toLocaleString()}</b>
          <span>folder grants today</span>
        </div>
        <div className="tile hl">
          <b>{assigns.toLocaleString()}</b>
          <span>role assignments after</span>
        </div>
        <div className="tile">
          <b>{U.filter(u => u.new_role_count === 1).length}</b>
          <span>need one role</span>
        </div>
        <div className="tile">
          <b>{wide}</b>
          <span>need more than three</span>
        </div>
      </div>

      <div className="note g">
        The drop from {grants.toLocaleString()} to {assigns.toLocaleString()} is
        inheritance doing the work: a grant on a department is redundant once someone
        holds the faculty above it. Nothing was widened to achieve it — where a wider
        role <i>would</i> be simpler, the row says so and leaves the decision to AKU.
      </div>

      <div className="bar">
        <input
          type="search"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search a name, email, role or SharePoint group — try Ambreen…"
        />
        <span className="hits">
          {rows.length} of {U.length} people
        </span>
      </div>
      <div className="bar">
        <button className={`btn ${cap === '' ? 'on' : ''}`} onClick={() => setCap('')}>
          Everyone
        </button>
        {rd.ladder
          .slice()
          .reverse()
          .filter(c => byCap[c])
          .map(c => (
            <button
              key={c}
              className={`btn ${cap === c ? 'on' : ''}`}
              onClick={() => setCap(c)}
            >
              {c}
              <b className="bc">{byCap[c]}</b>
            </button>
          ))}
        <label className="tg">
          <input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} />
          only the {simplifiable} worth simplifying
        </label>
      </div>

      <div className="ulist">
        {rows.slice(0, 300).map(u => {
          const isOpen = who === u.login
          const newRoles = u.new_roles ? u.new_roles.split('; ') : []
          const oldGroups = u.old_groups ? u.old_groups.split('; ') : []
          return (
            <div key={u.login}>
              <div
                className={`urow ${isOpen ? 'sel' : ''}`}
                onClick={() => setWho(isOpen ? '' : u.login)}
              >
                <div className={`av ${u.top_capability}`}>{initials(u.name)}</div>
                <div className="pi">
                  <b>{u.name}</b>
                  <span>{u.email || u.login}</span>
                </div>
                <span className="cmp">{CAMPUS[u.campus] || u.campus}</span>

                <span className="side old">
                  <i>{u.old_group_count}</i> group{u.old_group_count === 1 ? '' : 's'}
                  <em>{u.folders_before_collapse} folder grants</em>
                </span>
                <span className="arrow">→</span>
                <span className="side neu">
                  <i>{u.new_role_count}</i> role{u.new_role_count === 1 ? '' : 's'}
                  <em>
                    {u.highest_tier ? `${TIER_LABEL[u.highest_tier]} tier` : ''}
                  </em>
                </span>

                <span className={`cap2 ${u.top_capability}`}>{u.top_capability}</span>
                {u.simplify_to ? (
                  <span className="tip" title={u.simplify_to}>
                    simplify
                  </span>
                ) : (
                  <span className="tip ghost" />
                )}
              </div>

              {isOpen && (
                <div className="udet">
                  <div className="ucol">
                    <h5>Today · SharePoint</h5>
                    <ul className="tagl">
                      {oldGroups.map(g => (
                        <li key={g}>
                          <code>{g}</code>
                        </li>
                      ))}
                    </ul>
                    <h5>Permissions held</h5>
                    <p className="sm dim">{u.old_role_strings}</p>
                  </div>

                  <div className="ucol">
                    <h5>Tomorrow · Storyblok</h5>
                    <ul className="tagl">
                      {newRoles.map(r => {
                        const rr = roleById.get(r)
                        return (
                          <li key={r}>
                            <code>
                              <b>{r}</b>
                            </code>
                            {rr && (
                              <span className="sm dim">
                                {' '}
                                — {rr.tier === 'functional' ? rr.means : rr.means}
                              </span>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                    {u.simplify_to && (
                      <div className="note" style={{ margin: '10px 0 0' }}>
                        <b>Could be simpler.</b> {u.simplify_to}. That is a{' '}
                        <i>wider</i> grant than they hold today, so it is AKU's call —
                        nothing here applied it.
                      </div>
                    )}
                  </div>

                  <div className="ucol wide">
                    <h5>
                      Where they work — {u.folders_before_collapse} folder grants become{' '}
                      {u.folders_after_collapse}
                    </h5>
                    <ul className="tagl">
                      {(u.scopes ? u.scopes.split('; ') : []).map(s => (
                        <li key={s}>
                          <code>{s.replace(/^regions\//, '')}</code>
                        </li>
                      ))}
                    </ul>
                    {!u.scopes && (
                      <p className="dim sm">
                        No folder scope — their access is space-wide or functional.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
        {rows.length > 300 && (
          <div className="more">
            Showing the first 300 of {rows.length} — narrow the search to see the rest.
          </div>
        )}
      </div>
    </section>
  )
}
