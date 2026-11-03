// t261103_24_docs_read_face.mjs — the documents READ path (src/host/docs.ts:
// readDocsSelection / docsIndexFace) on the roots the docs-roots change rewired.
//
// Why this battery exists (t261103-24): the docs-roots delivery added the read path
// without one unit case for it, and the read answered 500 for EVERY readable page
// (a path predicate was called but never defined; the tree legs stayed green, so the
// hole shipped). What this file pins, on the public shape only (no private naming, no
// execution order — an internal rewrite that keeps these answers must stay green):
//   A. a plain page read SERVES the page it was asked for (the regression itself);
//   B. the transport form the tree hands back (`@<n>/<rel>`) serves the same page;
//   C. a refusal is an ANSWER with its own named reason, never an empty page: unknown
//      root selection / path shape / no root holding the page are told apart;
//   D. the derived-index face travels with every answer and NEVER takes the read down:
//      absent state, an unreadable index record and a refused declaration all answer
//      with a named banner while the document is still served;
//   E. the read never writes: no index directory is created by reading.
//
// Hermetic: temp repository + temp projects root (SANDBAR_PROJECTS_DIR for the whole
// process), no network, no real ~/.sandbar, no port, no docker; every temp directory is
// reclaimed in this file's exit hook.
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readDocsSelection, docsRootsTree } from '../src/host/docs.ts'

const tmpDirs = []
function fresh(prefix) {
  const d = mkdtempSync(join(tmpdir(), prefix))
  tmpDirs.push(d)
  return d
}
function reclaimAll() {
  for (const d of tmpDirs) {
    try { rmSync(d, { recursive: true, force: true }) } catch { /* already gone */ }
  }
  tmpDirs.length = 0
}
process.on('exit', reclaimAll)

// One projects root for the WHOLE battery: every bare path helper (index state read,
// index directory) resolves inside it, so no call here can reach the real ~/.sandbar.
const PROJECTS_ROOT = fresh('t261103-24-projects-')
process.env.SANDBAR_PROJECTS_DIR = PROJECTS_ROOT

const FM = (title) => `---\ntitle: ${title}\ncategory: reference\nstatus: active\n---\n\n`
const BODY = 'Body of the fixture page.\n'

/** A fixture repository holding docs/ (the implied root) with two pages. */
function repoFixture() {
  const root = fresh('t261103-24-repo-')
  mkdirSync(join(root, 'docs', 'sub'), { recursive: true })
  writeFileSync(join(root, 'docs', 'mini.md'), FM('Fixture guide') + '# Fixture heading\n\n' + BODY)
  writeFileSync(join(root, 'docs', 'sub', 'deep.md'), FM('Fixture deep page') + '# Deep heading\n')
  return root
}

// The default context of the console (no registry entry): the implied `docs` root of the
// repository root the caller names.
const REPO = repoFixture()
const OPTS = { repos: [REPO], noDeclaration: true }
const KEY = 'fixa'
const INDEX_FILE = join(PROJECTS_ROOT, KEY, 'data', 'docs', 'index.json')

let passed = 0
const cases = []
function test(name, fn) { cases.push([name, fn]) }
function ok(cond, label, detail = '') {
  assert.ok(cond, detail === '' ? label : `${label} — ${detail}`)
}

/* ---- A/B: the read serves the page (t261103-24 regression) ---- */

test('A: a plain page read serves title and body (a lone undefined name must never 500)', async () => {
  const r = await readDocsSelection(KEY, OPTS, 'mini.md')
  ok(r.state === 'served', 'state=served', `state=${r.state} reason=${r.reason ?? ''}`)
  ok(r.root === '.:docs', 'root token names the root in effect', `root=${r.root}`)
  ok(r.result.empty === false, 'page is not reported empty')
  ok(r.result.title === 'Fixture guide', 'title comes from the page frontmatter', `title=${r.result.title}`)
  ok(r.result.body.includes('Fixture heading'), 'body is the page text')
})

test('B: the transport token form the tree hands back serves the same page', async () => {
  const tree = await docsRootsTree(KEY, OPTS)
  const rels = tree.groups.flatMap((g) => g.files.map((f) => f.rel))
  ok(rels.includes('mini.md') || rels.includes('@0/mini.md'), 'tree lists the page', `rels=${rels.join(',')}`)
  for (const sel of ['mini.md', '@0/mini.md']) {
    const r = await readDocsSelection(KEY, OPTS, sel)
    ok(r.state === 'served' && r.result.title === 'Fixture guide',
      `selection ${sel} serves the page`, `state=${r.state} reason=${r.reason ?? ''}`)
  }
  const nested = await readDocsSelection(KEY, OPTS, 'sub/deep.md')
  ok(nested.state === 'served' && nested.result.title === 'Fixture deep page',
    'a page in a sub-directory serves too', `state=${nested.state}`)
})

/* ---- C: refusals name what failed, and they are answers (never an empty page) ---- */

test('C1: an unknown root selection is refused by name, listing the roots in effect', async () => {
  const r = await readDocsSelection(KEY, OPTS, '@9/mini.md')
  ok(r.state === 'refused', 'state=refused')
  ok(/unknown root selection/.test(r.reason), 'reason names the unknown selection', `reason=${r.reason}`)
  ok(r.reason.includes('@9'), 'reason echoes the selection that failed')
})

test('C2: a path that cannot be one plain safe page is refused by THAT reason', async () => {
  for (const sel of ['../../etc/passwd', '/abs.md', 'a b.md', 'notes.txt', '@0/@1/mini.md']) {
    const r = await readDocsSelection(KEY, OPTS, sel)
    ok(r.state === 'refused', `selection ${sel} is refused`, `state=${r.state}`)
    ok(/path not admitted/.test(r.reason),
      `selection ${sel} names the admission check`, `reason=${r.reason}`)
    ok(r.result === undefined, `selection ${sel} carries no page`)
  }
})

test('C3: a safe path no root holds is refused with the roots it looked in', async () => {
  const r = await readDocsSelection(KEY, OPTS, 'no-such-page.md')
  ok(r.state === 'refused', 'state=refused')
  ok(/exists under none of the documentation roots/.test(r.reason),
    'reason says the page is under none of the roots', `reason=${r.reason}`)
  ok(r.reason.includes('.:docs'), 'reason names the roots in effect')
})

/* ---- D: the derived-index face never takes the read down ---- */

test('D1: with no index built yet the page still serves and the face says so', async () => {
  const r = await readDocsSelection(KEY, OPTS, 'mini.md')
  ok(r.index !== undefined, 'every answer carries the index face')
  ok(r.index.state === 'absent', 'state=absent when no index exists', `state=${r.index.state}`)
  ok(r.index.banner.length > 0, 'the face carries a banner for the reader')
  ok(r.result.body.length > 0, 'the document is served anyway')
})

test('D2: an unreadable index record degrades the face NAMED and the page still serves', async () => {
  mkdirSync(join(PROJECTS_ROOT, KEY, 'data', 'docs'), { recursive: true })
  writeFileSync(INDEX_FILE, '{ this is not json')
  const r = await readDocsSelection(KEY, OPTS, 'mini.md')
  ok(r.state === 'served', 'the read is still served', `state=${r.state} reason=${r.reason ?? ''}`)
  ok(r.index.state === 'failed', 'the face reports the unreadable index', `state=${r.index.state}`)
  ok(r.result.title === 'Fixture guide', 'the page itself is unaffected')
  ok(r.index.reason.includes(INDEX_FILE), 'the named reason quotes the index path', `reason=${r.index.reason}`)
  ok(r.index.banner.length > 0 && r.index.banner !== 'Index not built yet — the documentation inspection builds it on its own pass. Documents are listed from the declared roots.',
    'the banner does not read as "no index yet" when an index record is broken')
})

test('D3: a refused declaration answers with its named reason AND the face (never a 500)', async () => {
  // The declaration names a root the repository does not hold: a named refusal, not an
  // empty view.
  const r = await readDocsSelection(KEY, { repos: [REPO],
    declarationText: 'paths:\n  docs_roots:\n    - repository: .\n      path: docs-missing\n' }, 'mini.md')
  ok(r.state === 'refused', 'state=refused', `state=${r.state}`)
  ok(r.reason.includes(join(REPO, 'docs-missing')), 'the refusal names the root it looked for', `reason=${r.reason}`)
  ok(r.index !== undefined && r.index.state === 'failed', 'the face reports the refused declaration')
  ok(r.index.banner.length > 0, 'the face carries a banner')
})

/* ---- E: reading never writes ---- */

test('E: the read creates no index directory (only the broken record planted here exists)', async () => {
  const before = existsSync(INDEX_FILE) ? readFileSync(INDEX_FILE, 'utf8') : null
  await readDocsSelection(KEY, OPTS, 'mini.md')
  await readDocsSelection(KEY, OPTS, 'sub/deep.md')
  const after = existsSync(INDEX_FILE) ? readFileSync(INDEX_FILE, 'utf8') : null
  ok(before === after, 'the index record is byte-identical after two reads')
  const otherKey = 'notreadkey'
  await readDocsSelection(otherKey, OPTS, 'mini.md')
  ok(!existsSync(join(PROJECTS_ROOT, otherKey)), 'a read for a project with no data directory creates none')
})

/* ---- F: import/call parity on the endpoint module (the second half of t261103-24) ---- */

test('F: every host-docs helper the endpoint CALLS is imported by the endpoint', async () => {
  // Source-text parity lock, not a behaviour assert. The docs-roots delivery dropped
  // `readDoc` from the endpoint's import while its notes-scope call site stayed, so the
  // notes page read threw `readDoc is not defined` and answered 500 — the same class as
  // the docs read. The helper set is taken from the module's own runtime exports, so a
  // helper added later is covered without editing this case.
  const hostDocs = await import('../src/host/docs.ts')
  const endpoint = readFileSync(new URL('../node.ts', import.meta.url), 'utf8')
  const clause = /import\s*\{([^}]*)\}\s*from\s*'\.\/src\/host\/docs\.ts'/.exec(endpoint)
  ok(clause !== null, 'the endpoint imports the host-docs module by that path')
  const imported = new Set(clause[1].split(',').map((s) => s.trim().replace(/^type\s+/, '')).filter(Boolean))
  const calledButNotImported = []
  for (const name of Object.keys(hostDocs)) {
    if (!/^[A-Za-z_$][\w$]*$/.test(name)) continue
    if (!new RegExp(`(?<![\\w$.])${name}\\s*\\(`).test(endpoint)) continue
    if (!imported.has(name)) calledButNotImported.push(name)
  }
  ok(calledButNotImported.length === 0, 'no host-docs helper is called without being imported',
    `called but not imported: ${calledButNotImported.join(', ')}`)
})

/* ---- runner ---- */

for (const [name, fn] of cases) {
  try {
    await fn()
    passed += 1
    console.log(`  ok ${name}`)
  } catch (e) {
    console.error(`FAIL ${name}\n    ${String(e?.message ?? e).split('\n').slice(0, 6).join('\n    ')}`)
    reclaimAll()
    process.exit(1)
  }
}
reclaimAll()
console.log(`DOCS_READ_FACE_TESTS ran=${cases.length} pass=${passed} fail=0`)
