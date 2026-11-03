/**
 * smoke/docs-roots.mjs — the knowledge feature's half of t261103-12
 * (design docs/design/project-docs-roots-v1.md).
 *
 * What it pins here (the console view's half lives in
 * server/plugins/workbench/tests/t261103_12_docs_roots.mjs):
 *   1. the plugin module still LOADS with the root resolution wired in (a host-side
 *      import error would otherwise surface only when the console starts);
 *   2. the legacy doc-path rule still admits today's category paths and still refuses
 *      traversal (the declared-root admission was added BESIDE it, not instead of it);
 *   3. a document path is located through the resolved roots: one holder wins, an
 *      ambiguous or missing path is refused by name, an explicit root id wins;
 *   4. the index-state copy keeps the three states apart — a stale index never reads
 *      as current.
 *
 * Direct run: node smoke/docs-roots.mjs (in server/plugins/knowledge/ or any cwd).
 * Zero temp dirs, zero network, zero writes.
 */
import assert from 'node:assert/strict'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { DOC_PATH_CATEGORIES, DOC_PATH_RE, name } from '../node.ts'
import {
  SECTION_LABEL, STOP, indexBanner, locateRoot, parseDeclaration, parseRootToken,
  resolveDocsRoots, splitRootToken,
} from '../src/shared/docs-roots.ts'

let pass = 0
let fail = 0
function ok(cond, label, detail = '') {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------------------- 1. the host module loads */
section('1. the plugin module loads')
ok(name === 'sandbar-knowledge', 'the plugin name is unchanged')
ok(typeof DOC_PATH_RE?.test === 'function', 'the doc-path rule is compiled')
ok(Array.isArray([...DOC_PATH_CATEGORIES]) && DOC_PATH_CATEGORIES.length > 0,
  'the legacy admission vocabulary is still present')

/* ------------------------------------- 2. the legacy path rule is unchanged */
section('2. the legacy doc-path rule still admits today\'s paths')
ok(DOC_PATH_RE.test('design/x.md'), 'a category path is admitted')
ok(DOC_PATH_RE.test('epics/anything.md'), 'the epic store is admitted')
ok(!DOC_PATH_RE.test('../escape.md'), 'traversal is refused')
ok(!DOC_PATH_RE.test('/abs/x.md'), 'absolute paths are refused')
ok(!DOC_PATH_RE.test('design/nested/x.md'), 'nested paths stay outside the legacy rule')

/* ------------------------------------------ 3. root location over the roots */
section('3. a page is located through the resolved roots')
const rootA = { id: '.:kb', repository: '.', path: 'kb', directory: '/nonexistent-a/kb', state: 'served', projections: [] }
const rootB = { id: 'repo-b:kb', repository: 'repo-b', path: 'kb', directory: '/nonexistent-b/kb', state: 'served', projections: [] }
const one = { project: 'p', state: 'served', source: 'declared', declaration: 'd.yaml',
  roots: [rootA], projections: [], reason: '', code: '', lookedFor: [] }
const two = { ...one, roots: [rootA, rootB] }
// The fixture paths do not exist on disk, so `locateRoot` must answer from the
// existence probe: nothing is found, and the refusal names the roots it searched.
const none = locateRoot(one, 'kb/x.md', null)
ok('reason' in none && none.reason.includes('exists under none'), 'a missing page names the roots it searched')
const named = locateRoot(two, 'kb/x.md', rootB.id)
ok('root' in named && named.root.id === rootB.id, 'an explicit root id wins')
const unknown = locateRoot(two, 'kb/x.md', '/nope:kb')
ok('reason' in unknown && unknown.reason.includes('unknown root'), 'an unknown root id is refused by name')
const empty = locateRoot({ ...one, roots: [] }, 'kb/x.md', null)
ok('reason' in empty, 'no root in effect is a named refusal, not a silent pick')

/* -------------------------------- 3b. the declaration is paths.docs_roots */
section('3b. the declaration shape')
ok(SECTION_LABEL === 'paths.docs_roots', 'the declaration lives inside the project declaration')
ok(parseDeclaration('paths:\n  docs_roots:\n    - repository: .\n      path: kb\n', 'p.yaml')?.[0]?.path === 'kb',
  'one declared root parses')
let malformed = ''
try {
  parseDeclaration('paths:\n  docs_roots:\n    - repo: .\n      path: kb\n', 'p.yaml')
} catch (err) { malformed = String(err.code) }
ok(malformed === STOP.declarationMalformed, 'a malformed block is refused by name', malformed)
const refused = resolveDocsRoots('ghost-project-key', { repos: ['/nonexistent'], projectsRootDir: '/nonexistent-projects' })
ok(refused.state === 'refused' && refused.code === STOP.absent,
  'an undeclared project with no docs directory is a named refusal, not an empty list', refused.code)

/* --------------------------------------------- 4. the three states' copy */
section('4. the index states stay distinguishable in the copy')
const absent = indexBanner({ state: 'absent', project: 'p', builtAt: '', staleReason: '', reason: '', entries: [], roots: [], total: 0 })
const stale = indexBanner({ state: 'stale', project: 'p', builtAt: '2026-11-03T10:00:00.000Z',
  staleReason: 'a document is newer than the build', reason: '', entries: [], roots: [], total: 0 })
const failed = indexBanner({ state: 'failed', project: 'p', builtAt: '2026-11-03T10:00:00.000Z',
  staleReason: '', reason: 'disk full', entries: [], roots: [], total: 0 })
const current = indexBanner({ state: 'current', project: 'p', builtAt: '2026-11-03T10:00:00.000Z',
  staleReason: '', reason: '', entries: [], roots: [], total: 0 })
ok(absent.includes('not built yet'), 'absent says the index was never built')
ok(stale.includes('stale') && stale.includes('2026-11-03T10:00:00.000Z') && /rebuild is due/.test(stale),
  'stale says stale, gives the last build time, and says a rebuild is due')
ok(!stale.toLowerCase().includes('up to date'), 'stale never reads as current')
ok(failed.includes('disk full') && failed.includes('NOT shown as current'),
  'failed names its reason and says the old index is not current')
ok(current.includes('up to date'), 'current names the build time')

/* ------------------------------------------------ 5. the selection token */
section('5. the selection token round-trips')
ok(splitRootToken('@1/kb/x.md') === 'kb/x.md', 'a token splits back to the path')
ok(splitRootToken('kb/x.md') === 'kb/x.md', 'a plain single-root path passes through')
const parsed = parseRootToken('@0/kb/x.md')
ok(parsed.rootIndex === 0 && parsed.rel === 'kb/x.md', 'the parser keeps the root index')

const total = pass + fail
console.log(`\nT261103_12_KNOWLEDGE_DOCS_ROOTS ${pass}/${total} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
