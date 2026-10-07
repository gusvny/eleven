/**
 * Baseline: JSX children-position comment guard (ticket t261008-02).
 *
 * Intent:
 *   A three-line `//` comment sat in JSX children position in the machine-status
 *   head (between the workers button and the Inspection-jump button). In children
 *   position `//` is TEXT, not a comment, so the comment shipped verbatim into
 *   the rendered DOM (confirmed: the literal string was present 3x in each shipped
 *   bundle before the fix). JSX children comments must use the brace-star form.
 *   This baseline locks two faces so the pattern cannot come back silently:
 *     - src: no line in any shipped `.tsx` under server/plugins matches the
 *       family sweep pattern (a run of `//` comment lines whose previous
 *       non-blank line ends with `>` / `)` / `}` and whose next non-blank line
 *       starts with `<` or `{`) — the same heuristic the host used for the
 *       family-wide sweep; guards the whole family, not just the one site.
 *     - bundles: the offending literal must not ship in `lib/client.js` /
 *       `lib/client.cjs`; in src it is allowed only inside a JSX comment block.
 *   Known trade-off (carried over from the spec-card-ui.mjs static-lock family,
 *   review_plan comment 1): this proves text absence from the shipped bundles,
 *   not a live browser render — the visual face (middle-column screenshot, and
 *   "rendered head text contains no `//`") belongs to the integration gate.
 *   Wording note (review_plan comment 2): the assertions are "this literal must
 *   not ship" and "no new children-position `//` lines" — not the over-broad
 *   "no `//` can ever render" (an intentional string could legally contain it).
 *   Pure node — no server, no Temporal, no browser; runs anywhere (including
 *   the engine's mechanical integration step).
 */

import { readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { readdirSync } from 'node:fs'

const REPO = process.cwd()
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'index.tsx')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const PLUGINS = join(REPO, 'server', 'plugins')
const LITERAL = 't261005-10 (UI-2): the number stays machine-level'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---- 1. bundle triple-lock: the offending literal must not ship ---- */
section('offending literal absent from shipped bundles')
for (const [path, mustBeAbsent] of [[LIB_JS, true], [LIB_CJS, true]]) {
  let text = null
  try { text = readFileSync(path, 'utf8') } catch { text = null }
  ok(text !== null, `${relative(REPO, path)} readable (stale-bundle lock is real)`)
  if (text === null) continue
  ok(!text.includes(LITERAL), `${relative(REPO, path)} does not ship the children-position comment text`)
}

/* ---- 2. src: the literal survives only inside a JSX comment block ---- */
section('src keeps the note as a real JSX comment ({/* ... */})')
let src = null
try { src = readFileSync(SRC, 'utf8') } catch { src = null }
ok(src !== null, 'src/client/index.tsx readable')
if (src !== null) {
  ok(src.includes(LITERAL), 'src still carries the explanatory note (not deleted outright)')
  // Strip every {/* ... */} block (non-greedy, no nesting in this codebase), then
  // the literal must be gone: i.e. it existed only inside a JSX comment.
  const stripped = src.replace(/\{\/\*[\s\S]*?\*\//g, '')
  ok(!stripped.includes(LITERAL), 'the note lives ONLY inside a {/* ... */} block')
  ok(/\{\/\* t261005-10 \(UI-2\): the number stays machine-level/.test(src),
    'the note is a JSX comment at the machine-status head site')
}

/* ---- 3. family sweep guard: no children-position `//` comment lines ---- */
section('family sweep: no `//` comment line in JSX children position (server/plugins *.tsx)')
const SWEEP_PREV = /[>)}`]\s*$/
const SWEEP_NEXT = /^\s*[<{]/
function listTsx(dir, acc) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules') continue
    const p = join(dir, e.name)
    if (e.isDirectory()) listTsx(p, acc)
    else if (e.name.endsWith('.tsx')) acc.push(p)
  }
  return acc
}
const tsxFiles = listTsx(PLUGINS, [])
ok(tsxFiles.length > 0, `scanned ${tsxFiles.length} .tsx files under server/plugins`)
const offenders = []
for (const f of tsxFiles) {
  const lines = readFileSync(f, 'utf8').split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (!/^\s*\/\//.test(lines[i])) continue
    const prev = lines[i - 1]
    if (prev === undefined || !SWEEP_PREV.test(prev)) continue
    let j = i
    while (j < lines.length && /^\s*\/\//.test(lines[j])) j++
    const next = lines[j]
    if (next !== undefined && SWEEP_NEXT.test(next)) offenders.push(`${relative(REPO, f)}:${i + 1}`)
    i = j
  }
}
ok(offenders.length === 0,
  offenders.length === 0
    ? 'no children-position `//` comment line anywhere under server/plugins'
    : `children-position \`//\` comment line(s) found (these render as DOM text): ${offenders.join(', ')}`)
ok(offenders.length === 0 || !offenders.some((o) => o.startsWith('server/plugins/workbench/src/client/index.tsx')),
  'the original t261008-02 site stays fixed')

console.log(`\njsd-comment-children pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
