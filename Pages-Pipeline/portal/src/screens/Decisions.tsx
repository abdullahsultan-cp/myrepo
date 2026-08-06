/** The open questions, as a worklist.
 *
 *  Every other screen answers a question from the data. This one lists what the
 *  data cannot answer — the residue where the export, the permissions and the live
 *  site all agree on what the content *is* and still leave a choice about what to
 *  do with it. Ordered by pages at stake, because that is the order in which a
 *  wrong answer costs the most.
 */
import { useMemo, useState } from 'react'
import type { Data } from '../lib/store'
import { DECISION_GROUPS, DECISION_BLURB } from '../lib/types'

export default function Decisions({ d }: { d: Data }) {
  const [group, setGroup] = useState('all')
  const all = d.plan.decisions || []

  const groups = useMemo(() => {
    const seen = new Set(all.map(x => x.group))
    return DECISION_GROUPS.filter(g => seen.has(g))
  }, [all])

  const rows = useMemo(() => {
    const list = group === 'all' ? all : all.filter(x => x.group === group)
    return [...list].sort((a, b) => b.pages - a.pages || a.question.localeCompare(b.question))
  }, [all, group])

  const pages = rows.reduce((n, r) => n + r.pages, 0)
  const atStake = all.reduce((n, r) => n + r.pages, 0)
  const blocking = rows.filter(r => r.blocks).length
  // One shared scale, so a bar means the same width on every row and after any
  // filter — rescaling per view would make a 3-page decision look like a 25-page one.
  const widest = Math.max(1, ...all.map(r => r.pages))

  return (
    <section>
      <h2>Decisions AKU owes us</h2>
      <p className="lede">
        Everything else in this portal is <b>derived</b> — from AKU&rsquo;s page list, from the
        SharePoint permissions export, or from a page I opened on aku.edu. These{' '}
        {all.length} are what is left over: the export says what the content <i>is</i> and
        still leaves a choice about what to <i>do</i> with it. They are generated from the
        plan, so answering one and rebuilding removes it from this list.
      </p>

      <div className="tiles">
        {([
          [all.length, 'open decisions', true],
          [atStake, 'pages waiting on one', false],
          [all.filter(r => r.blocks).length, 'block a review', false],
          [(d.plan.pages.length - atStake).toLocaleString(), 'pages needing no decision', false],
        ] as [number | string, string, boolean][]).map(([v, l, hl]) => (
          <div className={`tile ${hl ? 'hl' : ''}`} key={l}>
            <b>{v}</b>
            <span>{l}</span>
          </div>
        ))}
      </div>

      <div className="bar">
        <button className={`btn${group === 'all' ? ' on' : ''}`} onClick={() => setGroup('all')}>
          Everything <i>{all.length}</i>
        </button>
        {groups.map(g => (
          <button
            key={g}
            className={`btn${group === g ? ' on' : ''}`}
            onClick={() => setGroup(g)}
          >
            {g} <i>{all.filter(x => x.group === g).length}</i>
          </button>
        ))}
        <span className="hits">
          {rows.length} shown · {pages} pages · {blocking} blocking
        </span>
      </div>

      {group !== 'all' && <p className="lede">{DECISION_BLURB[group]}</p>}

      <div className="tw2 dec">
        <table>
          <thead>
            <tr>
              <th>The question</th>
              <th>What we observed</th>
              <th>The options</th>
              <th className="num">Pages at stake</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td>
                  <b>{r.question}</b>
                  {group === 'all' && <span className="chip">{r.group}</span>}
                  {r.blocks && (
                    <span className="chip amber" title={r.blocks}>blocks a review</span>
                  )}
                  {r.example_paths && (
                    <div className="dpaths">
                      {r.example_paths.split('; ').map(p => (
                        <code key={p}>{p}</code>
                      ))}
                      {r.folders > 4 && <span className="mut"> +{r.folders - 4} more</span>}
                    </div>
                  )}
                </td>
                <td className="sm">{r.evidence}</td>
                <td className="sm">
                  <ol className="dopts">
                    {r.options.split(' | ').map(o => <li key={o}>{o}</li>)}
                  </ol>
                </td>
                <td className="num">
                  <span className="dnum">{r.pages || '—'}</span>
                  {r.pages > 0 && (
                    <span className="dbar" aria-hidden="true">
                      <i style={{ width: `${(r.pages / widest) * 100}%` }} />
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
