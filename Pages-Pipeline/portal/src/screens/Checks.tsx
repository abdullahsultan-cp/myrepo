import type { Data } from '../lib/store'
import { strip } from '../lib/types'

export default function Checks({ d }: { d: Data }) {
  return (
    <section>
      <h2>Confirmed against the live site</h2>
      <p className="lede">
        Where the two exports disagreed or said nothing, I opened the page on aku.edu and read the
        breadcrumb AKU itself renders — that breadcrumb <i>is</i> the canonical parent, because the
        site is stating where it thinks the page lives.
      </p>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Page opened</th>
              <th>What AKU shows</th>
              <th>What it settles</th>
            </tr>
          </thead>
          <tbody>
            {d.plan.live.map(x => (
              <tr key={x.page_checked}>
                <td>
                  <a href={x.page_checked} target="_blank" rel="noopener">
                    <code>{strip(x.page_checked)}</code>
                  </a>
                </td>
                <td className="sm">{x.what_aku_shows}</td>
                <td className="sm">{x.what_it_settles}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
