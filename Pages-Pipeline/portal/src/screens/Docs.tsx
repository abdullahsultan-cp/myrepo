import type { Data } from '../lib/store'

/** Reference tables, one row per column. The meanings are NOT written here: they
 *  ship in plan.json beside the column lists that produce the CSVs, so a renamed
 *  column cannot leave a stale description behind in a second file. */
function ColumnTable({ cols }: { cols: [string, string][] }) {
  return (
    <div className="tw2">
      <table>
        <thead>
          <tr>
            <th>Column</th>
            <th>Means</th>
          </tr>
        </thead>
        <tbody>
          {cols.map(([c, m]) => (
            <tr key={c}>
              <td>{c}</td>
              <td className="sm">{m}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Docs({ d }: { d: Data }) {
  const F = d.plan.folders
  const P = d.plan.pages
  const cols = d.plan.columns
  const decisions = d.plan.decisions || []
  const n = (x: number) => x.toLocaleString()

  const inferred = F.filter(f => f.confidence !== 'witnessed')
  const shared = F.filter(f => f.also_belongs_to)
  const archive = F.filter(f => f.archive_candidate)
  const events = F.filter(f => f.event_owner)
  const ownPerms = F.filter(f => f.own_permissions === 'yes')
  const collisions = P.filter(p => p.collision)
  const update = P.filter(p => p.action === 'Update and move')

  // file, one row per, rows, how to check it
  const files: [string, string, string, string][] = [
    ['aku-folder-map.csv', 'destination folder', n(F.length),
     'Sort by pages_subtree and read the top rows — those are the folders worth arguing about.'],
    ['aku-page-map.csv', 'page', n(P.length),
     'Pick a page you know and compare current_url with new_url.'],
    ['aku-permission-groups.csv', 'role, flat model', n(d.plan.roles.length),
     'Superseded by the role hierarchy, kept so an old link still resolves.'],
    ['aku-role-hierarchy.csv', 'custom Storyblok role', n(d.rd.roles.length),
     'Read a role id — pakistan.medical-college.anaesthesiology.contributor says its own scope.'],
    ['aku-user-roles.csv', 'named person', n(d.rd.users.length),
     'Find yourself: old_groups on the left, new_roles on the right.'],
    ['aku-old-role-inventory.csv', 'SharePoint group', n(d.rd.old_groups.length),
     'Every group AKU has today and the role that replaces it. Nothing is dropped silently.'],
    ['aku-old-role-strings.csv', 'SharePoint role string', n(d.rd.old_strings.length),
     'Where “Design” and “Limited Access” went.'],
    ['aku-role-capabilities.csv', 'action × capability', n(d.rd.matrix.length),
     'What each rung of the ladder may actually do.'],
    ['aku-live-page-checks.csv', 'page opened on aku.edu', n(d.plan.live.length),
     'Open the URL and see whether it still shows what the row claims.'],
    ['aku-site-visits.csv', 'URL considered', '—',
     'Filter status — “remaining” is what the sweep has not reached yet.'],
    ['AKU-Folder-Hierarchy.tree.txt', 'line of the tree', '—',
     'Search it in any editor. No browser needed.'],
    ['AKU-Migration-Portal.html', '—', '—',
     'This app, as one file. Double-click it — no server, no network, nothing to install.'],
  ]

  return (
    <section className="doc">
      <h2>How this was built</h2>
      <p className="lede">
        Nothing here is an opinion about AKU&rsquo;s structure. Two exports and the live site decided
        every row, and every row records which one decided it. This page says where the inputs came
        from, how to rebuild the outputs, and what each column means — so a number you disagree with
        can be traced to the rule that produced it.
      </p>

      <h3>The three inputs</h3>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Input</th>
              <th>Authoritative for</th>
              <th>Blind to</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>aku-university-visible-pages.csv</td>
              <td className="sm">
                <b>What moves.</b> {n(P.length)} pages, each with AKU&rsquo;s own disposition —{' '}
                {n(P.length - update.length)} move as is, {n(update.length)} need content work first.
              </td>
              <td className="sm">
                Structure and ownership. Its <code>Type</code> column is always
                &ldquo;Unknown&rdquo;, <code>Webparts</code> always FALSE, <code>LastModified</code>{' '}
                entirely empty — only <code>FileName</code>, <code>PageUrl</code> and{' '}
                <code>Action</code> carry information.
              </td>
            </tr>
            <tr>
              <td>SharePoint_2016_User_Roles_Mapping.csv</td>
              <td className="sm">
                <b>Who owns what.</b> 102,011 permission rows; the 83,052 whose site collection is{' '}
                <code>http://aku.edu</code> describe 611 webs, their real titles, their owner groups,
                the AD domain of every account, and the {n(d.rd.old_strings.length)} distinct
                permission strings those accounts hold.
              </td>
              <td className="sm">
                Pages — it lists webs only. And 42 of the 82 sections in it hold no page at all,
                which is why the two files have to be joined rather than either used alone.
              </td>
            </tr>
            <tr>
              <td>aku.edu itself</td>
              <td className="sm">
                <b>Every call the exports could not make.</b> Entity or not, which countries a unit
                works in, who runs an event, whether a page still exists.{' '}
                {n(d.plan.live.length)} pages opened and read.
              </td>
              <td className="sm">
                Nothing, but the sweep is not finished. <code>aku-site-visits.csv</code> lists the
                URLs visited <i>and</i> the ones still to check, so the gap is stated rather than
                hidden.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="note">
        <b>Two traps in the permissions export, both of which cost real time.</b> Only rows with{' '}
        <code>Permission Scope = Unique</code> name an owner — inherited rows repeat the AKU-wide
        groups (AKU Owners, Designers, Hierarchy Managers) into every folder and witness nothing. And
        31 folders are Unique but list the site&rsquo;s entire group roster, 47 to 93 groups, where a
        genuinely owned folder carries 2 to 8. Nothing falls between 8 and 47, so those rosters are
        dropped on <code>groups &gt; 30</code>. Read ownership off them and every folder looks like it
        belongs to every region.
      </div>

      <h3>Rebuilding it</h3>
      <p className="lede" style={{ marginBottom: 10 }}>
        Each step writes the input the next one reads, so any step can be re-run alone once its
        predecessor has. Nothing touches the network: the live-site findings are recorded in{' '}
        <code>site_visits.py</code> as a checklist, not fetched at build time.
      </p>
      <div className="card">
        <pre>{`cd Pages-Pipeline/build

python probe_csv.py             # permissions CSV -> sites.json          (aku.edu rows only)
python join.py                  # + the page list -> pages.json          + join_report.txt
python sections.py              # unique-scope rows -> webs.json         + sections.txt
python probe_roles.py           # owner groups -> groups.json, web_owners.json
python extract_regions.py       # region witnesses -> region_witnesses.json
python build_hierarchy.py       # -> ../AKU-Folder-Hierarchy.{html,tree.txt,json}
python build_migration_plan.py  # -> the folder, page and live-check CSVs + plan.json
python probe_people.py          # -> people.json + people_probe.txt
python build_roles.py           # -> the five role CSVs + roles.json

cp plan.json people.json roles.json ../portal/public/data/`}</pre>
      </div>
      <div className="card">
        <pre>{`cd Pages-Pipeline/portal

npm install                     # once
npm run build                   # -> dist/ AND ../AKU-Migration-Portal.html
npm run dev                     # http://localhost:5173, while working on it`}</pre>
      </div>
      <div className="note g">
        <b>The deliverable is one file.</b> <code>npm run build</code> ends by folding the script,
        the stylesheet and all three datasets into{' '}
        <code>Pages-Pipeline/AKU-Migration-Portal.html</code> — it opens by double-click, with no
        server and no network. Served normally the same code fetches{' '}
        <code>data/*.json</code> instead, so there is one implementation and two ways of shipping it.
        Rebuilding is the only way to refresh that file, which is what stops it drifting from the
        data. <code>build/render_portal.py</code> is the earlier hand-written generator; it now
        writes <code>AKU-Migration-Portal-legacy.html</code> so it cannot overwrite this one.
      </div>

      <h3>What it writes</h3>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>One row per</th>
              <th>Rows</th>
              <th>Check it by</th>
            </tr>
          </thead>
          <tbody>
            {files.map(([f, per, rows, check]) => (
              <tr key={f}>
                <td>{f}</td>
                <td className="sm">{per}</td>
                <td className="num">{rows}</td>
                <td className="sm">{check}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>How a placement is decided</h3>
      <div className="card">
        <dl className="gl">
          <dt>Region</dt>
          <dd>
            Three witnesses, strongest first: a dedicated <code>CW &lt;X&gt;</code> /{' '}
            <code>CA &lt;X&gt;</code> pair, or a <code>FacultyOwners-&lt;x&gt;</code> group; then the
            AD domain in the login accounts as a majority over the folder&rsquo;s unique rows —{' '}
            <code>aku\</code> Karachi, <code>nbi\</code> Nairobi, <code>dar\</code> Dar es Salaam,{' '}
            <code>ismc\</code> London; then the folder&rsquo;s own SharePoint title when it names the
            country outright, as in &ldquo;Medical College, Kenya&rdquo;.
          </dd>
          <dt>Entity</dt>
          <dd>
            Not a judgement call: a unit is an entity when AKU publishes it on{' '}
            <code>aku.edu/academics</code> or <code>aku.edu/research</code>, and a folder at region
            level when it does not. <code>entity_basis</code> records which list it came from.
          </dd>
          <dt>Department</dt>
          <dd>
            A sub-folder becomes a <code>departments/</code> level only when the export proves it is
            a real unit with its own CW/CA group, the way <code>mcpk/anaes</code> is owned by
            Anaesthesiology. Everything else keeps its own slug, so no path segment is invented.
          </dd>
          <dt>Confidence</dt>
          <dd>
            <b>{n(F.length - inferred.length)}</b> of {n(F.length)} folders are <i>witnessed</i> —
            the export or the live page proves them.{' '}
            {inferred.length > 0 && (
              <>
                <b>{inferred.length}</b> {inferred.length === 1 ? 'is' : 'are'} <i>inferred</i>:{' '}
                {inferred.map((f, i) => (
                  <span key={f.new_path}>
                    {i > 0 && ', '}
                    <code>{f.new_path}</code>
                  </span>
                ))}
                . Treat those as questions, not as settled.
              </>
            )}
          </dd>
          <dt>Owner</dt>
          <dd>
            <b>{n(ownPerms.length)}</b> folders set their own permissions; the other{' '}
            {n(F.length - ownPerms.length)} inherit. Permissions are hierarchical, so whoever holds
            one on a folder manages that folder and everything under it. There is no unowned folder —
            it is always someone, just further up the tree.
          </dd>
        </dl>
      </div>

      {/* A plan.json generated before the column meanings moved into it would
          otherwise take the whole screen down with it. Say which step to re-run. */}
      {!cols ? (
        <div className="note">
          <b>The column meanings are missing from this plan.json.</b> They are generated beside the
          column lists that write the CSVs, so re-run <code>python build_migration_plan.py</code> and
          copy <code>plan.json</code> into <code>portal/public/data/</code>.
        </div>
      ) : (
        <>
          <h3>Every column, folder map</h3>
          <ColumnTable cols={cols.folders} />

          <h3>Every column, page map</h3>
          <ColumnTable cols={cols.pages} />

          <h3>Every column, the flat role list</h3>
          <ColumnTable cols={cols.roles} />
        </>
      )}

      <h3>What the build refuses to do</h3>
      <div className="card">
        <dl className="gl">
          <dt>Lose a folder or a page</dt>
          <dd>
            <code>build_hierarchy.py</code> exits non-zero if any web from the permissions export or
            any page from AKU&rsquo;s list fails to land somewhere in the tree. A silent drop would
            look exactly like a clean run.
          </dd>
          <dt>Guess at a new section</dt>
          <dd>
            The classification table in <code>classification.py</code> asserts against the CSV on
            every run. Add a section to aku.edu and the build stops until that table covers it —
            which is also why the generated files must never be hand-edited.
          </dd>
          <dt>Describe a column it no longer writes</dt>
          <dd>
            The column meanings on this page are checked against the CSV header on every run. Add a
            column without describing it, or describe one that has gone, and the build stops rather
            than shipping a documentation page that quietly lies.
          </dd>
          <dt>Resolve a collision quietly</dt>
          <dd>
            {collisions.length} pages want a slug another page already has. Both rows stay in the
            page map with the conflict named in <code>collision</code>, because picking one is
            AKU&rsquo;s call.
          </dd>
          <dt>Drop a page without a reason</dt>
          <dd>
            {n(d.dropped.length)} pages do not migrate, and each carries what the server actually
            returned when it was fetched — a 404, a 401, an empty SharePoint default page, or a
            duplicate hub listing that the single global hub supersedes.
          </dd>
        </dl>
      </div>

      <h3>Still open</h3>
      <div className="tw2">
        <table>
          <thead>
            <tr>
              <th>Count</th>
              <th>What needs a decision</th>
              <th>Where</th>
            </tr>
          </thead>
          <tbody>
            {decisions.length > 0 && (
              <tr>
                <td className="num">{decisions.length}</td>
                <td className="sm">
                  Questions the exports and the live site cannot answer between them — a private
                  section, a conference that has not run in years, a folder whose writer and whose
                  own page disagree. Each row states what was observed and the options.
                </td>
                <td className="sm">
                  <code>decisions</code> in plan.json
                </td>
              </tr>
            )}
            <tr>
              <td className="num">{inferred.length}</td>
              <td className="sm">Placements supported by a naming convention but not witnessed.</td>
              <td className="sm">
                <code>confidence = inferred</code> in the folder map
              </td>
            </tr>
            <tr>
              <td className="num">{collisions.length}</td>
              <td className="sm">Slug collisions — AKU picks which page keeps the address.</td>
              <td className="sm">
                <a href="#pages">Pages, old &amp; new</a>
              </td>
            </tr>
            <tr>
              <td className="num">{shared.length}</td>
              <td className="sm">
                Folders belonging to an entity they cannot live under. They need a tag or a
                cross-link, not a second home.
              </td>
              <td className="sm">
                <a href="#shared">Shared content</a>
              </td>
            </tr>
            <tr>
              <td className="num">{archive.length}</td>
              <td className="sm">
                Event microsites whose last edition is old enough to be archive rather than content
                to carry forward.
              </td>
              <td className="sm">
                <code>archive_candidate</code> in the folder map
              </td>
            </tr>
            <tr>
              <td className="num">{events.length}</td>
              <td className="sm">
                Event microsites whose owner was read off their own page — worth confirming with the
                unit named, since their SharePoint group is named after the event, not the faculty.
              </td>
              <td className="sm">
                <code>event_owner</code> in the folder map
              </td>
            </tr>
            <tr>
              <td className="num">{n(update.length)}</td>
              <td className="sm">
                Pages AKU marked &ldquo;Update and move&rdquo; — content work someone has to own
                before the move.
              </td>
              <td className="sm">
                <a href="#pages">Pages, old &amp; new</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>Not in scope</h3>
      <div className="note">
        The permissions export covers three site collections. Only <code>http://aku.edu</code> is
        planned here — <b>hospitals.aku.edu</b> (17,698 rows) and <b>examinationboard.aku.edu</b>{' '}
        (1,261) are separate institutions and need their own decision. <code>AKU-EN_1.HTM</code> in
        the source folder is an earlier generated view of the same page set, not a third source. And
        the {n(d.livePages.length)} pages here are pages: the 3,606 news stories are a separate
        migration, already live in Storyblok.
      </div>
    </section>
  )
}
