import { useEffect, useState } from 'react'
import { useData } from './lib/store'
import Overview from './screens/Overview'
import FolderTree from './screens/FolderTree'
import OrgChart from './screens/OrgChart'
import Pages from './screens/Pages'
import Rights from './screens/Rights'
import Roles from './screens/Roles'
import People from './screens/People'
import Model from './screens/Model'
import Hierarchy from './screens/Hierarchy'
import Users from './screens/Users'
import Decisions from './screens/Decisions'
import Shared from './screens/Shared'
import Checks from './screens/Checks'
import Glossary from './screens/Glossary'
import Docs from './screens/Docs'

const SCREENS = [
  { id: 'overview', label: 'Overview', group: 'Plan' },
  { id: 'tree', label: 'Folder structure', group: 'Plan' },
  { id: 'chart', label: 'Org chart', group: 'Plan' },
  { id: 'pages', label: 'Pages, old & new', group: 'Plan' },
  { id: 'model', label: 'How permissions work', group: 'Permissions' },
  { id: 'hierarchy', label: 'Role hierarchy', group: 'Permissions' },
  { id: 'users', label: 'Users, old → new', group: 'Permissions' },
  { id: 'rights', label: 'Folders that set rights', group: 'Permissions' },
  { id: 'decisions', label: 'Decisions AKU owes us', group: 'Detail' },
  { id: 'shared', label: 'Shared content', group: 'Detail' },
  { id: 'checks', label: 'Live-site checks', group: 'Detail' },
  { id: 'glossary', label: 'What words mean', group: 'Detail' },
  { id: 'docs', label: 'How this was built', group: 'Detail' },
]

export default function App() {
  const { data, error } = useData()
  const [route, setRoute] = useState(location.hash.slice(1) || 'overview')

  useEffect(() => {
    const on = () => setRoute(location.hash.slice(1) || 'overview')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  // Block body, not an expression body: an arrow that returns the value of
  // window.scrollTo hands that value to React as the effect's cleanup, and React
  // then calls it — "destroy is not a function", and a blank screen.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [route])

  if (error) {
    return (
      <div className="boot err">
        <b>Could not load the migration data.</b>
        <p>{error}</p>
        <p>
          This happens when <code>dist/index.html</code> is opened straight off the disk — the
          browser blocks reading <code>data/plan.json</code> from a <code>file://</code> page. Serve
          it instead:
        </p>
        <pre>
          cd Pages-Pipeline/portal{'\n'}
          npm run dev{'      '}# http://localhost:5173{'\n'}
          npm run preview{'  '}# serves the production build
        </pre>
      </div>
    )
  }
  if (!data) return <div className="boot">Loading the migration plan…</div>

  const counts: Record<string, string> = {
    tree: data.plan.folders.length.toLocaleString(),
    pages: data.livePages.length.toLocaleString(),
    roles: String(data.plan.roles.length),
    people: String(data.people.length),
    hierarchy: String(data.rd.roles.length),
    users: String(data.rd.users.length),
    rights: String(data.plan.folders.filter(f => f.own_permissions === 'yes').length),
    shared: String(data.plan.folders.filter(f => f.also_belongs_to).length),
    checks: String(data.plan.live.length),
    decisions: String((data.plan.decisions || []).length),
  }

  let body = null
  switch (route) {
    case 'tree': body = <FolderTree d={data} />; break
    case 'chart': body = <OrgChart d={data} />; break
    case 'pages': body = <Pages d={data} />; break
    case 'model': body = <Model d={data} />; break
    case 'hierarchy': body = <Hierarchy d={data} />; break
    case 'users': body = <Users d={data} />; break
    case 'rights': body = <Rights d={data} />; break
    // the flat-model screens, kept reachable by hash so a link in an old email
    // still opens: #roles and #people
    case 'roles': body = <Roles d={data} />; break
    case 'people': body = <People d={data} />; break
    case 'decisions': body = <Decisions d={data} />; break
    case 'shared': body = <Shared d={data} />; break
    case 'checks': body = <Checks d={data} />; break
    case 'glossary': body = <Glossary d={data} />; break
    case 'docs': body = <Docs d={data} />; break
    default: body = <Overview d={data} />
  }

  let lastGroup = ''
  return (
    <>
      <aside>
        <h1>AKU → Storyblok</h1>
        <p className="sub">
          {data.livePages.length.toLocaleString()} pages · {data.plan.folders.length} folders ·{' '}
          {data.plan.roles.length} roles
        </p>
        <nav>
          {SCREENS.map(s => {
            const head = s.group !== lastGroup ? ((lastGroup = s.group), s.group) : ''
            return (
              <div key={s.id}>
                {head && <div className="grp">{head}</div>}
                <a href={`#${s.id}`} className={route === s.id ? 'on' : ''}>
                  {s.label}
                  {counts[s.id] && <b>{counts[s.id]}</b>}
                </a>
              </div>
            )
          })}
        </nav>
      </aside>
      <main>{body}</main>
    </>
  )
}
