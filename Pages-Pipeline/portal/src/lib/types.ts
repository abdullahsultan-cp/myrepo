export type Folder = {
  new_path: string
  parent_path: string
  level: string | number
  kind: string
  region: string
  region_code: string
  entity: string
  title: string
  source_web: string
  pages_here: number | string
  pages_subtree: number | string
  managed_by: string
  can_create_and_edit: string
  can_publish: string
  can_add_or_delete_folders: string
  can_read_only: string
  countries: string
  entity_basis: string
  also_belongs_to: string
  event_owner: string
  last_ran: string
  archive_candidate: string
  own_permissions: string
  permission_source: string
  confidence: string
  provenance: string
}

export type Page = {
  current_url: string
  new_url: string
  new_path: string
  content_type: string
  action: string
  region: string
  region_code: string
  entity: string
  department: string
  folder: string
  moved_from: string
  managed_by: string
  countries: string
  confidence: string
  collision: string
  do_not_migrate: string
}

export type Role = {
  storyblok_role: string
  capability: string
  can_publish: string
  unit: string
  members: number
  folders_scoped: number
  source_sharepoint_groups: string
  allowed_paths: string
  note: string
}

export type LiveCheck = {
  page_checked: string
  what_aku_shows: string
  what_it_settles: string
}

export type Grant = {
  folder: string
  capability: string
  group: string
  unit: string
}

export type Person = {
  name: string
  email: string
  login: string
  campus: string
  top_capability: string
  groups: string[]
  folders: string[]
  grants: Grant[]
  storyblok_roles: string[]
}

/** A question the exports and the live site cannot answer between them — someone
 *  at AKU has to choose. Generated from the plan, so a resolved one disappears. */
export type Decision = {
  id: string
  group: string
  question: string
  evidence: string
  /** the choices, pipe-separated by the builder */
  options: string
  folders: number
  pages: number
  example_paths: string
  blocks: string
}

/** What every CSV column means, as ordered `[column, meaning]` pairs in the order
 *  the file writes them. Authored beside the column lists in
 *  build_migration_plan.py, which asserts that the two stay in step, so the docs
 *  screen describes the CSVs from one source rather than a second hand-kept copy. */
export type ColumnDocs = {
  folders: [string, string][]
  pages: [string, string][]
  roles: [string, string][]
}

export type Plan = {
  folders: Folder[]
  pages: Page[]
  roles: Role[]
  live: LiveCheck[]
  decisions: Decision[]
  columns: ColumnDocs
}

/** Ordered worst-first, which is also the order the screen groups them in. */
export const DECISION_GROUPS = [
  'not public', 'stale', 'ownership', 'finished', 'anomaly', 'do not migrate',
]

export const DECISION_BLURB: Record<string, string> = {
  'not public': 'AKU’s list says migrate these, but the section does not answer to '
    + 'the public — so nobody can review the content before it moves.',
  stale: 'The page names no edition since ' + '2024' + '. Carrying it forward '
    + 'publishes a conference or a magazine that has not run in years.',
  ownership: 'Who writes it and how it presents itself disagree. Both readings are '
    + 'defensible; the folder path can only follow one.',
  finished: 'The programme’s own page says it has ended or is not admitting.',
  anomaly: 'Live on aku.edu and absent from the migrate list, or present twice.',
  'do not migrate': 'Already excluded, listed here so the exclusion is visible '
    + 'rather than silent.',
}

/* ---- the custom role hierarchy, from build_roles.py -------------------- */

/** One custom role: a rung of the capability ladder at one scope. */
export type CustomRole = {
  role: string
  tier: string
  capability: string
  scope_path: string
  scope_folders: number | string
  parent_role: string
  can_publish: string
  unit: string
  members: number
  replaces_groups: string
  old_role_strings: string
  provenance: string
  means: string
  note: string
}

/** One action, and whether each rung of the ladder may do it. */
export type MatrixRow = Record<string, string>

/** One SharePoint group, and the custom role it becomes. */
export type OldGroup = {
  sharepoint_group: string
  kind: string
  unit: string
  members: number
  permission_rows: number
  old_role_strings: string
  old_capability: string
  new_roles: string
  new_role_count: number
  folders_owned: number
}

/** One of the 34 distinct SharePoint role strings, and what it translates to. */
export type OldString = {
  old_role_string: string
  permission_rows: number
  new_capability: string
  plus_functional_role: string
  means: string
  note: string
}

/** One person: what they hold on aku.edu today, and what to give them. */
export type UserRole = {
  name: string
  email: string
  login: string
  campus: string
  top_capability: string
  highest_tier: string
  new_role_count: number
  new_roles: string
  simplify_to: string
  old_group_count: number
  old_groups: string
  old_role_strings: string
  folders_before_collapse: number
  folders_after_collapse: number
  scopes: string
}

export type RolesData = {
  roles: CustomRole[]
  matrix: MatrixRow[]
  ladder: string[]
  tiers: string[]
  functional: string[]
  means: Record<string, string>
  old_groups: OldGroup[]
  old_strings: OldString[]
  users: UserRole[]
}

/** Plain-English label for each tier, and how far its reach goes. */
export const TIER_LABEL: Record<string, string> = {
  space: 'Space',
  region: 'Region',
  entity: 'Entity',
  department: 'Department',
  section: 'Section',
  functional: 'Functional',
}
export const TIER_REACH: Record<string, string> = {
  space: 'every folder in the space',
  region: 'one country, and every entity in it',
  entity: 'one faculty or institute, and its departments',
  department: 'one department, and its sections',
  section: 'one section or microsite',
  functional: 'a space-wide resource, not a folder',
}

/** The order AKU's own menus use, so every folder reads the same way. */
export const CANON = [
  'about', 'about-us', 'at-a-glance', 'academics', 'admissions', 'research',
  'supportus', 'support-us', 'students', 'alumni', 'faculty', 'media',
  'careers', 'library', 'libraries', 'news', 'events', 'blogs',
  'registrar', 'convocation', 'geo', 'leads', 'chancellor', 'trustees',
  'president', 'provostoffice', 'officers', 'charters', 'environment',
  'programmes', 'programs', 'study', 'departments', 'centres', 'partners',
  'resources', 'people', 'staff', 'contact', 'giving', 'impact',
]
export const RANK = new Map(CANON.map((n, i) => [n, i]))

export const KIND_LABEL: Record<string, string> = {
  root: 'top level',
  container: 'grouping',
  region: 'region',
  entity: 'entity',
  department: 'department',
  division: 'programme',
  section: 'section',
  folder: 'folder',
  'region-folder': 'region folder',
  centre: 'centre',
  office: 'office',
  publication: 'publication',
}

export const CAMPUS: Record<string, string> = {
  aku: 'Karachi',
  nbi: 'Nairobi',
  dar: 'Dar es Salaam',
  ismc: 'London',
  scholar: 'service account',
}

export const leaf = (p: string) => p.split('/').pop() || p
export const strip = (p: string) => p.replace(/^https?:\/\/[^/]+/, '')
