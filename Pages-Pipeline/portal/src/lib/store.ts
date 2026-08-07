import { useEffect, useState } from 'react'
import type { CustomRole, Folder, Page, Person, Plan, RolesData } from './types'
import { RANK } from './types'
import { buildPerm, type Perm } from './perm'

export type Data = {
  plan: Plan
  people: Person[]
  byPath: Map<string, Folder>
  kids: Map<string, string[]>
  roots: string[]
  pagesByFolder: Map<string, Page[]>
  pageByUrl: Map<string, Page>
  livePages: Page[]
  dropped: Page[]
  subPages: (p: string) => number
  subFolders: (p: string) => number
  /** every page at or below a folder, for the folder drawer */
  pagesUnder: (p: string) => Page[]
  perm: Perm
  regions: string[]
  kinds: string[]
  /** the custom role hierarchy */
  rd: RolesData
  roleById: Map<string, CustomRole>
  /** roles whose parent_role is this role — the hierarchy, walked downward */
  roleKids: Map<string, string[]>
}

const sortKey = (p: string) => {
  const n = p.split('/').pop() || p
  return [RANK.has(n) ? RANK.get(n)! : 500, n] as [number, string]
}
const cmp = (a: string, b: string) => {
  const [ra, na] = sortKey(a)
  const [rb, nb] = sortKey(b)
  return ra - rb || na.localeCompare(nb)
}

function build(plan: Plan, people: Person[], rd: RolesData): Data {
  const byPath = new Map(plan.folders.map(f => [f.new_path, f]))
  const kids = new Map<string, string[]>()
  for (const f of plan.folders) {
    if (!f.parent_path) continue
    const arr = kids.get(f.parent_path) || []
    arr.push(f.new_path)
    kids.set(f.parent_path, arr)
  }
  for (const [k, v] of kids) kids.set(k, v.sort(cmp))

  const roots = plan.folders
    .filter(f => !f.parent_path)
    .map(f => f.new_path)
    .sort((a, b) => (a === 'regions' ? -1 : b === 'regions' ? 1 : a.localeCompare(b)))

  const livePages = plan.pages.filter(p => p.new_path)
  const dropped = plan.pages.filter(p => !p.new_path)
  const pagesByFolder = new Map<string, Page[]>()
  for (const p of livePages) {
    const arr = pagesByFolder.get(p.folder) || []
    arr.push(p)
    pagesByFolder.set(p.folder, arr)
  }
  for (const [k, v] of pagesByFolder) {
    pagesByFolder.set(k, v.sort((a, b) => a.new_path.localeCompare(b.new_path)))
  }

  // memoised, because the tree asks for these on every render
  const pageCache = new Map<string, number>()
  const subPages = (p: string): number => {
    const hit = pageCache.get(p)
    if (hit !== undefined) return hit
    let n = (pagesByFolder.get(p) || []).length
    for (const c of kids.get(p) || []) n += subPages(c)
    pageCache.set(p, n)
    return n
  }
  const folderCache = new Map<string, number>()
  const subFolders = (p: string): number => {
    const hit = folderCache.get(p)
    if (hit !== undefined) return hit
    let n = 1
    for (const c of kids.get(p) || []) n += subFolders(c)
    folderCache.set(p, n)
    return n
  }

  const underCache = new Map<string, Page[]>()
  const pagesUnder = (p: string): Page[] => {
    const hit = underCache.get(p)
    if (hit) return hit
    const out = [...(pagesByFolder.get(p) || [])]
    for (const c of kids.get(p) || []) out.push(...pagesUnder(c))
    underCache.set(p, out)
    return out
  }

  const pageByUrl = new Map(plan.pages.map(p => [p.current_url, p]))
  const perm = buildPerm(plan, people, byPath)
  const regions = [...new Set(plan.folders.map(f => f.region).filter(Boolean))].sort()
  const kinds = [...new Set(plan.folders.map(f => f.kind).filter(Boolean))].sort()

  const roleById = new Map(rd.roles.map(r => [r.role, r]))
  const roleKids = new Map<string, string[]>()
  for (const r of rd.roles) {
    if (!r.parent_role) continue
    const arr = roleKids.get(r.parent_role) || []
    arr.push(r.role)
    roleKids.set(r.parent_role, arr)
  }
  for (const [k, v] of roleKids) roleKids.set(k, v.sort())

  return {
    plan, people, byPath, kids, roots, pagesByFolder, pageByUrl, livePages, dropped,
    subPages, subFolders, pagesUnder, perm, regions, kinds, rd, roleById, roleKids,
  }
}

/** The single-file build (`build_single.mjs`) stamps each dataset into the page as
 *  `<script type="application/json" id="aku-plan">…`, so the portal opens from a
 *  double-click with no server. Served normally, those tags are absent and the
 *  app fetches the same files — one code path, two ways of shipping it. */
const inlined = (id: string) => {
  const el = typeof document === 'undefined' ? null : document.getElementById(id)
  return el?.textContent ? JSON.parse(el.textContent) : null
}

export function useData() {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string>('')
  useEffect(() => {
    const baked = [inlined('aku-plan'), inlined('aku-people'), inlined('aku-roles')]
    const load = baked.every(Boolean)
      ? Promise.resolve(baked)
      : Promise.all([
        fetch('./data/plan.json').then(r => r.json()),
        fetch('./data/people.json').then(r => r.json()),
        fetch('./data/roles.json').then(r => r.json()),
      ])
    load
      .then(([plan, people, rd]) => setData(build(plan, people, rd)))
      .catch(err => setError(String(err)))
  }, [])
  return { data, error }
}

/** Permissions are hierarchical: a folder that sets none is managed by whoever
 *  manages the nearest folder above it that does. */
export function managerOf(d: Data, path: string): { label: string; own: boolean } {
  const self = d.byPath.get(path)
  if (self?.own_permissions === 'yes') return { label: self.managed_by, own: true }
  let cur = path
  while (cur.includes('/')) {
    cur = cur.slice(0, cur.lastIndexOf('/'))
    const f = d.byPath.get(cur)
    if (f?.own_permissions === 'yes') {
      return { label: 'inherits · ' + f.managed_by.split(';')[0].trim(), own: false }
    }
  }
  return { label: 'inherits from the space admin', own: false }
}
