/** Fold dist/ into one double-clickable file: Pages-Pipeline/out/AKU-Migration-Portal.html
 *
 *  The portal is handed to people who will not run npm, and a served build cannot
 *  be one of them — `fetch('./data/plan.json')` from a file:// page is blocked by
 *  the browser, which is why the app used to open on an error telling you to start
 *  a server. Inlining the script, the stylesheet and the three datasets removes
 *  that step entirely, and keeps a single implementation: `useData()` reads the
 *  baked-in tags when they exist and fetches the same files when they do not.
 *
 *  Run by `npm run build`, so the deliverable cannot drift from the source again.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.join(HERE, 'dist')
const DATA = path.join(HERE, 'public', 'data')
// out/ holds everything generated; the deliverable belongs beside the
// CSVs rather than loose in the Pages-Pipeline root.
const OUT = path.join(HERE, '..', 'out', 'AKU-Migration-Portal.html')

const read = f => fs.readFileSync(f, 'utf8')
const kb = n => (n / 1024 / 1024).toFixed(2) + ' MB'

/** A literal `</script>` inside the JSON would close the tag it lives in. Every
 *  `<` becomes the escape sequence for the same character, so JSON.parse yields
 *  an identical string and the element cannot terminate early. Ampersands are
 *  left alone: a non-executed script's body is not entity-decoded. */
const safeJson = src => src.replace(/</g, '\\u003c')

const html = read(path.join(DIST, 'index.html'))
const assets = fs.readdirSync(path.join(DIST, 'assets'))
const js = assets.find(f => f.endsWith('.js'))
const css = assets.find(f => f.endsWith('.css'))
if (!js || !css) throw new Error('dist/assets holds no js/css — run vite build first')

const DATASETS = [
  ['aku-plan', 'plan.json'],
  ['aku-people', 'people.json'],
  ['aku-roles', 'roles.json'],
]
const blocks = DATASETS.map(([id, file]) => {
  const src = read(path.join(DATA, file))
  JSON.parse(src)                     // fail here, not in the browser
  return `<script type="application/json" id="${id}">${safeJson(src)}</script>`
}).join('\n')

let out = html
  .replace(
    /<script type="module"[^>]*src="[^"]*"><\/script>/,
    () => `<script type="module">\n${read(path.join(DIST, 'assets', js))}\n</script>`,
  )
  .replace(
    /<link rel="stylesheet"[^>]*>/,
    () => `<style>\n${read(path.join(DIST, 'assets', css))}\n</style>`,
  )

if (out.includes('./assets/')) throw new Error('an asset reference survived inlining')

// A module script is deferred, so it runs only after the whole document is
// parsed — the data tags are in the DOM by the time useData() looks for them.
out = out.replace('<div id="root"></div>', `<div id="root"></div>\n${blocks}`)
if (!out.includes('id="aku-plan"')) throw new Error('data was not inlined')

fs.writeFileSync(OUT, out, 'utf8')
console.log(`single file  ${path.relative(path.join(HERE, '..', '..'), OUT)}  ${kb(Buffer.byteLength(out))}`)
