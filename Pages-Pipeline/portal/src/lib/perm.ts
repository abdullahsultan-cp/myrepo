/** Who can do what, to which folder and which page.
 *
 *  Two independent facts have to be joined to answer that, and they answer
 *  different halves of it:
 *
 *  - every folder names the Storyblok **roles** that may edit, publish, restructure
 *    and read it (`can_create_and_edit` and friends). Inheriting folders carry the
 *    resolved role names too, so a folder always knows its own answer;
 *  - every person carries the **roles** they end up in, and the folders they were
 *    granted on in SharePoint.
 *
 *  Role is the join. A folder lists `iedpk-publisher`; whoever holds that role is
 *  a publisher there. `grants` is kept beside it because it is the stronger claim:
 *  it says the permission is set *on that folder*, not inherited from above.
 *
 *  134 of the 276 roles have no named member — the SharePoint group exists but no
 *  Unique-scope row names a person in it. That is reported, never papered over: a
 *  folder whose only editor role is empty has nobody who can edit it today.
 */
import type { Folder, Page, Person, Plan, Role } from './types'

export const CAP_RANK: Record<string, number> = {
  admin: 0, structure: 1, publisher: 2, editor: 3, translator: 4, viewer: 5,
}
/** The order every list of capabilities is shown in. */
export const CAP_ORDER = ['admin', 'publisher', 'editor', 'structure', 'translator', 'viewer']

export const CAP_VERB: Record<string, string> = {
  admin: 'everything, including permissions',
  structure: 'add, move and delete folders',
  publisher: 'write, and publish to the public site',
  editor: 'write and save drafts — cannot publish',
  translator: 'translate existing content',
  viewer: 'read only',
}

/** What each capability may do to a page. Drives the page drawer, so it is the
 *  one place the CRUD answer is written down. */
export const CAN: Record<string, { create: boolean; edit: boolean; publish: boolean; del: boolean }> = {
  admin: { create: true, edit: true, publish: true, del: true },
  structure: { create: false, edit: false, publish: false, del: true },
  publisher: { create: true, edit: true, publish: true, del: false },
  editor: { create: true, edit: true, publish: false, del: false },
  translator: { create: false, edit: true, publish: false, del: false },
  viewer: { create: false, edit: false, publish: false, del: false },
}

export type Grant = { folder: string; capability: string; group: string; unit: string }

/** One named person's standing on one folder. */
export type Who = {
  person: Person
  capability: string
  /** the folder the grant is actually set on — self, or the ancestor it comes from */
  where: string
  direct: boolean
  /** the SharePoint group or Storyblok role that carries it */
  via: string
  /** `space` is the 21 space admins, who reach every folder. Kept apart from the
   *  folder's own team: counted in with them, every folder reads "21 admins" and
   *  the 3 people who actually run it disappear. */
  scope: 'folder' | 'space'
}

export type Rights = {
  /** the folder whose permissions actually apply here */
  source: string
  inherited: boolean
  managed_by: string
  edit: string[]
  publish: string[]
  structure: string[]
  read: string[]
}

/** Folder-scoped counts. `spaceWide` is the constant 21 admins on top. */
export type Counts = {
  admin: number; publisher: number; editor: number; viewer: number
  total: number; spaceWide: number
}

const parts = (s: string) => (s || '').split(';').map(x => x.trim()).filter(Boolean)

export type Perm = {
  byLogin: Map<string, Person>
  roleByName: Map<string, Role>
  roleMembers: Map<string, Person[]>
  /** grants set *on* a folder, i.e. where SharePoint broke inheritance */
  grantsAt: Map<string, { person: Person; grant: Grant }[]>
  spaceAdmins: Person[]
  structureManagers: Person[]
  rightsOf: (path: string) => Rights
  peopleOf: (path: string) => Who[]
  countsOf: (path: string) => Counts
  /** what this person may do here, or null. Walks up, so an ancestor grant counts. */
  capOf: (login: string, path: string) => { capability: string; where: string; direct: boolean; via: string } | null
  /** every folder the person can touch, deepest grant wins */
  reachOf: (login: string) => Map<string, { capability: string; where: string; direct: boolean }>
  /** roles named by folders but held by nobody */
  emptyRoles: Set<string>
}

export function buildPerm(
  plan: Plan,
  people: Person[],
  byPath: Map<string, Folder>,
): Perm {
  const byLogin = new Map(people.map(p => [p.login, p]))
  const roleByName = new Map(plan.roles.map(r => [r.storyblok_role, r]))

  const roleMembers = new Map<string, Person[]>()
  for (const p of people) {
    for (const r of p.storyblok_roles) {
      const arr = roleMembers.get(r) || []
      arr.push(p)
      roleMembers.set(r, arr)
    }
  }
  for (const [k, v] of roleMembers) {
    roleMembers.set(k, v.sort((a, b) => a.name.localeCompare(b.name)))
  }

  const grantsAt = new Map<string, { person: Person; grant: Grant }[]>()
  for (const p of people) {
    for (const g of p.grants as Grant[]) {
      const arr = grantsAt.get(g.folder) || []
      arr.push({ person: p, grant: g })
      grantsAt.set(g.folder, arr)
    }
  }

  const spaceAdmins = people.filter(p => p.storyblok_roles.includes('space-admin'))
  const structureManagers = people.filter(p => p.storyblok_roles.includes('structure-manager'))

  const emptyRoles = new Set<string>()
  for (const f of plan.folders) {
    for (const r of [...parts(f.can_create_and_edit), ...parts(f.can_publish)]) {
      if (!roleMembers.has(r)) emptyRoles.add(r)
    }
  }

  /** The folder whose permissions apply here: itself if it sets any, else the
   *  nearest one above it that does. Mirrors SharePoint's Unique scope. */
  const srcCache = new Map<string, { source: string; inherited: boolean }>()
  const sourceOf = (path: string) => {
    const hit = srcCache.get(path)
    if (hit) return hit
    const sets = (p: string) => byPath.get(p)?.own_permissions === 'yes' || grantsAt.has(p)
    let out = { source: path, inherited: false }
    if (!sets(path)) {
      let cur = path
      out = { source: '', inherited: true }
      while (cur.includes('/')) {
        cur = cur.slice(0, cur.lastIndexOf('/'))
        if (sets(cur)) { out = { source: cur, inherited: true }; break }
      }
    }
    srcCache.set(path, out)
    return out
  }

  const rightsOf = (path: string): Rights => {
    const f = byPath.get(path)
    const { source, inherited } = sourceOf(path)
    return {
      source,
      inherited,
      managed_by: f?.managed_by || '',
      // the plan already resolves these onto every folder, inheriting ones included
      edit: parts(f?.can_create_and_edit || ''),
      publish: parts(f?.can_publish || ''),
      structure: parts(f?.can_add_or_delete_folders || ''),
      read: parts(f?.can_read_only || ''),
    }
  }

  const peopleCache = new Map<string, Who[]>()
  const peopleOf = (path: string): Who[] => {
    const hit = peopleCache.get(path)
    if (hit) return hit
    const best = new Map<string, Who>()
    /** One entry per person. A grant on the folder beats a space-wide role even
     *  when the space-wide role is stronger — a space admin who is also this
     *  team's publisher belongs in the team, not in the space-wide footnote. */
    const take = (w: Who) => {
      const cur = best.get(w.person.login)
      if (!cur) { best.set(w.person.login, w); return }
      if (cur.scope !== w.scope) {
        if (w.scope === 'folder') best.set(w.person.login, w)
        return
      }
      if (CAP_RANK[w.capability] < CAP_RANK[cur.capability]) best.set(w.person.login, w)
    }

    // named grants, on this folder or the one it inherits from
    const { source } = sourceOf(path)
    for (const p of [path, source].filter(Boolean)) {
      for (const { person, grant } of grantsAt.get(p) || []) {
        take({
          person, capability: grant.capability, where: p, direct: p === path,
          via: grant.group || grant.unit, scope: 'folder',
        })
      }
    }

    // whoever holds a role this folder names — the answer for inheriting folders,
    // which carry resolved role names but no grant of their own
    const r = rightsOf(path)
    const fromRole = (roles: string[], capability: string, scope: 'folder' | 'space') => {
      for (const role of roles) {
        for (const person of roleMembers.get(role) || []) {
          take({ person, capability, where: r.source || path, direct: false, via: role, scope })
        }
      }
    }
    fromRole(r.publish, 'publisher', 'folder')
    fromRole(r.edit.filter(x => !r.publish.includes(x)), 'editor', 'folder')
    // can_add_or_delete_folders is `space-admin; structure-manager` on all 628 —
    // it is a space-level right, not this folder's team
    fromRole(r.structure, 'structure', 'space')

    for (const p of spaceAdmins) {
      take({ person: p, capability: 'admin', where: '', direct: false, via: 'space-admin', scope: 'space' })
    }

    const out = [...best.values()].sort(
      (a, b) => (a.scope === b.scope ? 0 : a.scope === 'folder' ? -1 : 1) ||
        CAP_RANK[a.capability] - CAP_RANK[b.capability] ||
        Number(b.direct) - Number(a.direct) ||
        a.person.name.localeCompare(b.person.name),
    )
    peopleCache.set(path, out)
    return out
  }

  const countCache = new Map<string, Counts>()
  const countsOf = (path: string): Counts => {
    const hit = countCache.get(path)
    if (hit) return hit
    const c: Counts = { admin: 0, publisher: 0, editor: 0, viewer: 0, total: 0, spaceWide: 0 }
    for (const w of peopleOf(path)) {
      if (w.scope === 'space') { c.spaceWide++; continue }
      if (w.capability in c) (c as any)[w.capability]++
      c.total++
    }
    countCache.set(path, c)
    return c
  }

  const reachCache = new Map<string, Map<string, { capability: string; where: string; direct: boolean }>>()
  const reachOf = (login: string) => {
    const hit = reachCache.get(login)
    if (hit) return hit
    const out = new Map<string, { capability: string; where: string; direct: boolean }>()
    const person = byLogin.get(login)
    if (!person) { reachCache.set(login, out); return out }

    const isAdmin = person.storyblok_roles.includes('space-admin')
    const isStructure = person.storyblok_roles.includes('structure-manager')
    const roles = new Set(person.storyblok_roles)
    const granted = new Map((person.grants as Grant[]).map(g => [g.folder, g]))

    for (const f of plan.folders) {
      const path = f.new_path
      let cap = ''
      let where = ''
      let direct = false

      // a grant on the folder, or on anything above it, cascades down
      let cur: string | null = path
      while (cur) {
        const g = granted.get(cur)
        if (g) {
          cap = g.capability
          where = cur
          direct = cur === path
          break
        }
        cur = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : null
      }

      // otherwise, a role the folder names and they hold
      if (!cap) {
        const r = rightsOf(path)
        if (r.publish.some(x => roles.has(x))) { cap = 'publisher'; where = r.source }
        else if (r.edit.some(x => roles.has(x))) { cap = 'editor'; where = r.source }
      }
      if (isAdmin && (!cap || CAP_RANK.admin < CAP_RANK[cap])) { cap = 'admin'; where = '' }
      else if (isStructure && !cap) { cap = 'structure'; where = '' }

      if (cap) out.set(path, { capability: cap, where, direct })
    }
    reachCache.set(login, out)
    return out
  }

  const capOf = (login: string, path: string) => {
    const r = reachOf(login).get(path)
    return r ? { ...r, via: '' } : null
  }

  return {
    byLogin, roleByName, roleMembers, grantsAt, spaceAdmins, structureManagers,
    rightsOf, peopleOf, countsOf, capOf, reachOf, emptyRoles,
  }
}

/** Pages inherit their folder's permissions — there is no page-level grant in the
 *  export, and Storyblok scopes roles by folder path too. */
export const pageRights = (perm: Perm, page: Page) => perm.rightsOf(page.folder)
export const pagePeople = (perm: Perm, page: Page) => perm.peopleOf(page.folder)
