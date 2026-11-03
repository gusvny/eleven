/**
 * t261103-12 — documentation roots for the web consumers (design
 * docs/design/project-docs-roots-v1.md, index + presentation half).
 *
 * ONE declaration, checked from BOTH runtimes: every fixture writes a real
 * `project.yaml` with the `paths.docs_roots` block the engine resolver reads, and the
 * parity section runs the python resolver over the same bytes to prove the engine and
 * the console cannot disagree about the same project.
 *
 * What this battery pins (the ticket's own list):
 *   A. the declaration reader — the `paths.docs_roots` grammar, every malformed shape
 *      refused by name (`docs_roots_declaration_malformed` / `docs_roots_duplicate`);
 *   B. the resolution — implied default, declared one/many roots, identity includes
 *      repository + root, the named refusals (`docs_roots_absent` /
 *      `docs_roots_root_absent` / `docs_roots_repository_unknown`), present-but-empty
 *      distinguished from a refusal, and the retired sibling `docs_roots.yaml` ignored;
 *   C. the merged view — one view over one or many roots, equal relative paths from two
 *      roots both visible, a refusal rendered in place of a listing (never a silent
 *      blank), a present-but-empty root distinguished from a refusal;
 *   D. the derived index states — absent / stale (with the last build time) / failed
 *      (with its reason) / current — and the copy that labels them (a stale index never
 *      reads as current);
 *   E. the read path never writes: no index directory is created, no file is touched;
 *   F. the projection control: nothing is emitted unless the project declares it;
 *   G. cross-runtime parity on the same declaration bytes.
 *
 * Everything is hermetic: temp repositories + a temp projects root (SANDBAR_PROJECTS_DIR
 * for the whole process), no network, no real ~/.sandbar, no port 3099.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readdirSync, rmSync, utimesSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  IMPLIED_ROOT, SECTION_LABEL, STOP, indexBanner, indexDir, locateRoot, liveEntries,
  newestDocMtime, parseDeclaration, parseRootToken, readIndexState, resolveDocsRoots,
  splitRootToken,
} from '../../knowledge/src/shared/docs-roots.ts'
import { docsRootsTree } from '../src/host/docs.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(HERE, '..', '..', '..', '..')

let pass = 0
let fail = 0
const tmpDirs = []
function ok(cond, label, detail = '') {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function fresh(prefix) {
  const d = mkdtempSync(join(tmpdir(), prefix))
  tmpDirs.push(d)
  return d
}
function write(base, rel, text) {
  const p = join(base, rel)
  mkdirSync(dirname(p), { recursive: true })
  writeFileSync(p, text)
  return p
}
const FM = '---\ntitle: Page\ncategory: reference\ntags: [x]\nstatus: active\nupdated: 2026-11-01\n---\n\nbody\n'

// Hermetic projects root for the WHOLE battery: every bare path helper (indexDir /
// readIndexState / docsRootsTree) resolves inside it, so no call in this file can reach
// the real ~/.sandbar even by omission.
const PROJECTS_ROOT = fresh('t261103-12-projects-')
process.env.SANDBAR_PROJECTS_DIR = PROJECTS_ROOT
let keySeq = 0

/** `paths:` content for the given (repository, path, projections) entries. */
function rootsBlock(entries) {
  let out = '  docs_roots:\n'
  for (const e of entries) {
    out += `    - repository: ${e.repository ?? '.'}\n      path: ${e.path}\n`
    if (e.projections) out += `      projections: ${e.projections}\n`
  }
  return out
}

/** A temp project: a project root (dirs[0]), optional nested member repositories, and an
 *  optional `paths:` block. `repository: .` = the project root itself. */
function project(opts = {}) {
  const key = opts.key ?? `proj-${++keySeq}`
  const projectRoot = fresh(`t261103-12-${key}-`)
  for (const name of (opts.members ?? [])) mkdirSync(join(projectRoot, name), { recursive: true })
  const perkey = join(PROJECTS_ROOT, key)
  mkdirSync(perkey, { recursive: true })
  const body = 'schema: v1\nproject:\n  - key: ' + key + '\n    name: ' + key +
    '\n    dirs:\n      - ' + projectRoot + '\n' + (opts.paths === undefined ? '' : 'paths:\n' + opts.paths)
  writeFileSync(join(perkey, 'project.yaml'), body)
  return { key, projectRoot, perkey, projects: PROJECTS_ROOT }
}

function resolutionOf(fixture, extra = {}) {
  return resolveDocsRoots(fixture.key, { repos: [fixture.projectRoot], ...extra })
}

/** The python resolver's face over the same project declaration (parity section). */
function pythonFace(key) {
  const script = `import json, sys
sys.path.insert(0, ${JSON.stringify(join(REPO_ROOT, 'server', 'engine'))})
import docs_roots
try:
    res = docs_roots.project_roots(${JSON.stringify(key)})
    print(json.dumps({"state": "served", "source": res.source,
                      "roots": [r.identity for r in res.roots],
                      "root_states": [docs_roots.root_state(r) for r in res.roots],
                      "projections": list(res.projections())}))
except docs_roots.DocsRootsStop as e:
    print(json.dumps({"state": "refused", "code": e.code}))
`
  const out = execFileSync(process.env.PYTHON ?? 'python3', ['-c', script], { encoding: 'utf8' })
  return JSON.parse(out.trim().split('\n').pop())
}

/* ============================================================== A. the declaration */

section('A. the declaration reader (paths.docs_roots grammar)')
{
  const one = parseDeclaration('paths:\n  docs_roots:\n    - repository: .\n      path: kb\n', 'p.yaml')
  ok(Array.isArray(one) && one.length === 1 && one[0].path === 'kb', 'A1 one root parsed')
  // `repository: .` normalises to '' (the project root) — the same normalisation the
  // engine resolver applies, so both sides key identity on the same value.
  ok(one[0].repository === '' && one[0].projections.length === 0,
    'A2 repository: . normalises to the project root; no projection by default')

  const many = parseDeclaration('paths:\n  docs_roots:\n'
    + '    - repository: .\n      path: kb\n'
    + '    - repository: web\n      path: handbook\n      projections: entries,fulltext\n', 'p.yaml')
  ok(many.length === 2, 'A3 many roots parsed')
  ok(JSON.stringify(many[1].projections) === '["entries","fulltext"]', 'A4 projections declared per root')

  ok(parseDeclaration('schema: v1\npaths:\n  dsh_bin: /bin/sh\n', 'p.yaml') === null,
    'A5 an absent block is "nothing declared" (null), not an error')

  const bad = [
    ['unknown entry key', '    - repo: .\n      path: kb\n'],
    ['missing path', '    - repository: .\n'],
    ['absolute path', '    - repository: .\n      path: /etc\n'],
    ['parent segment', '    - repository: .\n      path: ../out\n'],
    ['trailing slash', '    - repository: .\n      path: kb/\n'],
    ['whole repository', '    - repository: .\n      path: .\n'],
    ['unknown projection', '    - repository: .\n      path: kb\n      projections: vectors\n'],
    ['no entries', ''],
  ]
  let refused = 0
  for (const [label, block] of bad) {
    try {
      parseDeclaration(`paths:\n  docs_roots:\n${block}`, 'p.yaml')
      ok(false, `A6 malformed refused: ${label}`)
    } catch (err) {
      refused++
      ok(err.code === STOP.declarationMalformed || err.code === STOP.duplicate,
        `A6 malformed refused with a code: ${label}`, String(err.code))
    }
  }
  ok(refused === bad.length, `A6 all ${bad.length} malformed shapes refused`)
  try {
    parseDeclaration('paths:\n  docs_roots:\n    - repository: .\n      path: kb\n'
      + '    - repository: .\n      path: kb\n', 'p.yaml')
    ok(false, 'A7 duplicate refused')
  } catch (err) {
    ok(err.code === STOP.duplicate, 'A7 duplicate root refused with its own code', String(err.code))
  }
  ok(!/repo/.test(SECTION_LABEL) && SECTION_LABEL === 'paths.docs_roots', 'A8 the declaration name is paths.docs_roots')
}

/* ============================================================= B. the resolution */

section('B. the resolution (three config states, never silent)')
{
  const implied = project()
  write(implied.projectRoot, 'docs/design/a.md', FM)
  const impliedRes = resolutionOf(implied)
  ok(impliedRes.state === 'served' && impliedRes.source === 'implied', 'B1 undeclared + docs/ = served (implied)')
  ok(impliedRes.roots.length === 1 && impliedRes.roots[0].path === IMPLIED_ROOT, 'B2 implied root is the default name')
  ok(impliedRes.roots[0].id === '.:docs', 'B3 identity is repository + root path')
  ok(impliedRes.projections.length === 0, 'B4 an implied root declares no projection')

  const absent = project()
  const absentRes = resolutionOf(absent)
  ok(absentRes.state === 'refused' && absentRes.code === STOP.absent, 'B5 undeclared + no docs/ = named refusal')
  ok(absentRes.reason.includes(join(absent.projectRoot, 'docs')), 'B6 the refusal names the path it looked for')
  ok(absentRes.reason.includes(SECTION_LABEL), 'B7 the refusal names the declaration key')
  ok(absentRes.lookedFor.length > 0, 'B8 the refusal carries its search list')

  const declared = project({ paths: rootsBlock([{ repository: '.', path: 'kb' }]) })
  write(declared.projectRoot, 'kb/x.md', FM)
  const declaredRes = resolutionOf(declared)
  ok(declaredRes.state === 'served' && declaredRes.source === 'declared', 'B9 a declared non-default root is served')
  ok(declaredRes.declaration.endsWith('project.yaml'), 'B10 the declaration is the project declaration file')

  const two = project({ members: ['repo-b'], paths: rootsBlock([
    { repository: '.', path: 'handbook' }, { repository: 'repo-b', path: 'handbook' }]) })
  mkdirSync(join(two.projectRoot, 'handbook'), { recursive: true })
  mkdirSync(join(two.projectRoot, 'repo-b', 'handbook'), { recursive: true })
  const twoRes = resolutionOf(two)
  ok(twoRes.roots.length === 2, 'B11 many roots resolved')
  ok(twoRes.roots[0].id !== twoRes.roots[1].id, 'B12 equal relative paths keep distinct identities')
  ok(twoRes.roots[1].repository === 'repo-b', 'B13 the member repository is named on the root')

  const moved = project({ paths: rootsBlock([{ repository: '.', path: 'moved' }]) })
  const movedRes = resolutionOf(moved)
  ok(movedRes.state === 'refused' && movedRes.code === STOP.rootAbsent, 'B14 a moved/absent declared root is refused')
  ok(movedRes.reason.includes('moved') && movedRes.declaration.endsWith('project.yaml'),
    'B15 the refusal names the declaration and the path')

  const unknownRepo = project({ paths: rootsBlock([{ repository: 'ghost', path: 'docs' }]) })
  ok(resolutionOf(unknownRepo).code === STOP.repositoryUnknown, 'B16 an unregistered repository is refused by name')

  const empty = project({ paths: rootsBlock([{ repository: '.', path: 'kb' }]) })
  mkdirSync(join(empty.projectRoot, 'kb'), { recursive: true })
  write(empty.projectRoot, 'kb/notes.txt', 'not a page\n')
  const emptyRes = resolutionOf(empty)
  ok(emptyRes.state === 'served' && emptyRes.roots[0].state === 'empty',
    'B17 present but empty is served and named empty (a content finding)')

  // One declaration only: a stray sibling file must change nothing.
  const stray = project()
  write(stray.projectRoot, 'docs/a.md', FM)
  writeFileSync(join(stray.perkey, 'docs_roots.yaml'),
    'schema: v1\ndocs_roots:\n  - repo: /elsewhere\n    path: kb\n')
  const strayRes = resolutionOf(stray)
  ok(strayRes.state === 'served' && strayRes.source === 'implied' && strayRes.roots[0].path === 'docs',
    'B18 the retired sibling docs_roots.yaml is ignored')
}

/* ============================================================ C. the merged view */

section('C. the merged console view over the resolved roots')
{
  const one = project()
  write(one.projectRoot, 'docs/design/a.md', FM)
  write(one.projectRoot, 'docs/root.md', FM)
  const treeOne = await docsRootsTree(one.key, { repos: [one.projectRoot] })
  ok(treeOne.state === 'served' && treeOne.empty === false, 'C1 one root: served, not empty')
  ok(treeOne.groups.length === 2, 'C2 one root: groups follow the actual directories')
  ok(treeOne.groups.every((g) => g.files.every((f) => f.root === '.:docs')), 'C3 every row names its root')
  ok(treeOne.roots[0].path === IMPLIED_ROOT, 'C4 the implied root is named in the view')
  ok(treeOne.groups.every((g) => /\.md$/.test(g.files[0].rel)), 'C5 single-root rows keep the plain path (no token)')

  const two = project({ members: ['repo-b'], paths: rootsBlock([
    { repository: '.', path: 'kb' }, { repository: 'repo-b', path: 'kb' }]) })
  write(two.projectRoot, 'kb/same.md', FM)
  write(two.projectRoot, 'repo-b/kb/same.md', FM)
  write(two.projectRoot, 'kb/only-left.md', FM)
  const treeTwo = await docsRootsTree(two.key, { repos: [two.projectRoot] })
  const rows = treeTwo.groups.flatMap((g) => g.files)
  ok(treeTwo.roots.length === 2, 'C6 many roots: both are in effect')
  ok(rows.length === 3, 'C7 every page of both roots is listed')
  ok(rows.some((r) => r.rel.startsWith('@')), 'C8 a colliding relative path carries a selection token')
  ok(rows.some((r) => r.rel === 'only-left.md'), 'C9 a unique relative path keeps the plain form')
  ok(treeTwo.groups.every((g) => /repo-b|kb/.test(g.label)), 'C10 merged labels name the root')
  ok(new Set(treeTwo.groups.map((g) => g.dir)).size === treeTwo.groups.length, 'C11 merged group keys are unique')

  const refused = project({ paths: rootsBlock([{ repository: '.', path: 'gone' }]) })
  const treeRef = await docsRootsTree(refused.key, { repos: [refused.projectRoot] })
  ok(treeRef.state === 'refused' && treeRef.code === STOP.rootAbsent, 'C12 a refusal is its own state, with a code')
  // The refusal reaches today's console page through the legacy `empty:true` branch,
  // which renders a named reason; `state:'refused'` keeps it distinguishable.
  ok(treeRef.empty === true && treeRef.groups.length === 0, 'C13 a refusal rides the reason-rendering branch')
  ok(treeRef.reason.includes('gone') && treeRef.declaration.endsWith('project.yaml'),
    'C14 the refusal names the path and the declaration')
  ok(treeRef.looked_for.length > 0, 'C15 the refusal carries the search list')

  const emptyRoot = project({ paths: rootsBlock([{ repository: '.', path: 'kb' }]) })
  mkdirSync(join(emptyRoot.projectRoot, 'kb'), { recursive: true })
  const treeEmpty = await docsRootsTree(emptyRoot.key, { repos: [emptyRoot.projectRoot] })
  ok(treeEmpty.state === 'served' && treeEmpty.empty === true, 'C16 present but empty is served + empty')
  ok(treeEmpty.reason.includes('present but empty'), 'C17 the empty answer says it is a content finding')
  ok(treeEmpty.roots.length === 1, 'C18 the empty answer still names the root it searched')
}

/* ========================================================= D. the index states */

section('D. the derived index: absent / stale / failed / current')
{
  const p = project()
  const page = write(p.projectRoot, 'docs/a.md', FM)
  const resolution = resolutionOf(p)

  const absent = readIndexState(p.key, resolution)
  ok(absent.state === 'absent', 'D1 no index yet = absent')
  ok(indexBanner(absent).includes('not built yet'), 'D2 absent copy says the index was never built')
  ok(!existsSync(indexDir(p.key)), 'D3 reading the index created nothing (no write on the read path)')

  const dir = indexDir(p.key)
  mkdirSync(dir, { recursive: true })
  const builtAt = new Date('2026-11-03T10:00:00.000Z')
  const writeIndex = (over = {}) => {
    writeFileSync(join(dir, 'index.json'), JSON.stringify({
      schema: 'v1', project: p.key, built_at: builtAt.toISOString(),
      built_at_ts: builtAt.getTime() / 1000, total: 1,
      roots: resolution.roots.map((r) => ({ identity: r.id })),
      docs: [{ id: `${resolution.roots[0].id}:a.md`, path: 'a.md', title: 'Page', category: 'reference' }],
      ...over,
    }))
  }
  writeIndex()
  utimesSync(page, new Date(builtAt.getTime() - 60_000), new Date(builtAt.getTime() - 60_000))
  const current = readIndexState(p.key, resolution)
  ok(current.state === 'current', 'D4 an index matching the documents = current')
  ok(indexBanner(current).includes('up to date') && current.builtAt === builtAt.toISOString(),
    'D5 current copy names the build time')

  utimesSync(page, new Date(builtAt.getTime() + 120_000), new Date(builtAt.getTime() + 120_000))
  const stale = readIndexState(p.key, resolution)
  ok(stale.state === 'stale', 'D6 a page newer than the build = stale')
  ok(stale.builtAt === builtAt.toISOString(), 'D7 stale carries the LAST BUILD TIME')
  ok(stale.staleReason.includes('newer than the build'), 'D8 stale names why a rebuild is due')
  const staleCopy = indexBanner(stale)
  ok(staleCopy.includes('stale') && staleCopy.includes(builtAt.toISOString()),
    'D9 stale copy says stale and gives the build time')
  ok(!staleCopy.includes('up to date'), 'D10 a stale index is NEVER presented as current')
  ok(stale.entries.length === 1, 'D11 stale entries are still returned (to be shown as stale)')

  const moved = project({ paths: rootsBlock([{ repository: '.', path: 'kb' }]) })
  mkdirSync(join(moved.projectRoot, 'kb'), { recursive: true })
  const movedDir = indexDir(moved.key)
  mkdirSync(movedDir, { recursive: true })
  writeFileSync(join(movedDir, 'index.json'), JSON.stringify({
    schema: 'v1', project: moved.key, built_at: builtAt.toISOString(),
    built_at_ts: builtAt.getTime() / 1000, total: 1, roots: [{ identity: '.:docs' }], docs: [],
  }))
  const movedRead = readIndexState(moved.key, resolutionOf(moved))
  ok(movedRead.state === 'stale' && movedRead.staleReason.includes('roots in effect changed'),
    'D12 a moved root leaves the old index stale (never looking current)')

  writeFileSync(join(dir, 'rebuild-failed.json'), JSON.stringify({
    schema: 'v1', project: p.key, failed_at_ts: (builtAt.getTime() / 1000) + 60,
    code: STOP.rootAbsent, reason: 'permission denied writing index' }))
  const failed = readIndexState(p.key, resolution)
  ok(failed.state === 'failed', 'D13 a newer rebuild failure = failed')
  ok(failed.reason.includes('permission denied') && failed.code === STOP.rootAbsent,
    'D14 failed carries its named reason and code')
  ok(failed.entries.length === 0, 'D15 a failed rebuild serves no old entries')
  ok(indexBanner(failed).includes('NOT shown as current'), 'D16 failed copy says the old index is not current')
  rmSync(join(dir, 'rebuild-failed.json'))
}

/* ==================================== E/F. live listing, projections, read-path */

section('E. read path never writes; F. projections stay opt-in')
{
  const p = project()
  write(p.projectRoot, 'docs/design/a.md', FM)
  const resolution = resolutionOf(p)
  const before = existsSync(join(PROJECTS_ROOT, p.key, 'data', 'docs'))
  const live = liveEntries(resolution)
  ok(live.length === 1 && live[0].category === 'reference', 'E1 live listing reads the roots (category from the document)')
  ok(live[0].id.startsWith(`${resolution.roots[0].id}:`), 'E2 live entries carry the full identity')
  ok(newestDocMtime(resolution.roots) !== null, 'E3 the staleness measurement is available to a reader')
  await docsRootsTree(p.key, { repos: [p.projectRoot] })
  ok(existsSync(join(PROJECTS_ROOT, p.key, 'data', 'docs')) === before,
    'E4 a read (view + index) creates nothing in the data directory')

  const engine = join(REPO_ROOT, 'server', 'engine', 'docs_index.py')
  ok(existsSync(engine), 'F0 the engine builder is present')
  const run = () => execFileSync(process.env.PYTHON ?? 'python3',
    [engine, '--project', p.key, '--projects-root', PROJECTS_ROOT, '--trigger', 'operator'],
    { encoding: 'utf8' })
  const outDefault = JSON.parse(run())
  ok(outDefault.ok === true, 'F1 builder ran (operator trigger)', JSON.stringify(outDefault).slice(0, 200))
  const data = indexDir(p.key)
  ok(existsSync(join(data, 'index.json')), 'F2 the index lands in the project data directory')
  ok(!existsSync(join(data, 'entries.json')) && !existsSync(join(data, 'fulltext.json')),
    'F3 no LLM projection by default (docs/ with no declaration gets none)')
  ok(!existsSync(join(p.projectRoot, 'docs', 'index.json')), 'F4 nothing is written inside the repository')

  const declared = project({ paths: rootsBlock([
    { repository: '.', path: 'docs', projections: 'entries,fulltext' }]) })
  write(declared.projectRoot, 'docs/a.md', FM)
  const outProj = JSON.parse(execFileSync(process.env.PYTHON ?? 'python3',
    [engine, '--project', declared.key, '--projects-root', PROJECTS_ROOT], { encoding: 'utf8' }))
  ok(outProj.ok === true, 'F5 builder ran with the projection declared')
  const dataProj = indexDir(declared.key)
  ok(existsSync(join(dataProj, 'entries.json')) && existsSync(join(dataProj, 'fulltext.json')),
    'F6 declared projections are emitted beside the index')
  const entries = JSON.parse(execFileSync('cat', [join(dataProj, 'entries.json')], { encoding: 'utf8' }))
  ok(entries.total === 1 && entries.entries[0].root === '.:docs', 'F7 the entry list carries the root identity')
  const readBack = readIndexState(declared.key, resolutionOf(declared))
  ok(readBack.state === 'current', 'F8 the console reader sees the fresh build as current')
}

/* ================================================ G. root location + parity */

section('G. root location for a consumer with no token, and cross-runtime parity')
{
  const two = project({ members: ['repo-b'], paths: rootsBlock([
    { repository: '.', path: 'kb' }, { repository: 'repo-b', path: 'kb' }]) })
  write(two.projectRoot, 'kb/only-left.md', FM)
  write(two.projectRoot, 'kb/shared.md', FM)
  write(two.projectRoot, 'repo-b/kb/shared.md', FM)
  const res = resolutionOf(two)

  const unique = locateRoot(res, 'only-left.md', null)
  ok('root' in unique && unique.root.repository === '.', 'G1 a path held by one root resolves to it')
  const ambiguous = locateRoot(res, 'shared.md', null)
  ok('reason' in ambiguous && ambiguous.reason.includes('name one with root='),
    'G2 a path held by two roots is refused by name (never a silent pick)')
  const absentPath = locateRoot(res, 'nowhere.md', null)
  ok('reason' in absentPath && absentPath.reason.includes('exists under none'),
    'G3 a path under no root names the roots it searched')
  const named = locateRoot(res, 'shared.md', res.roots[1].id)
  ok('root' in named && named.root.id === res.roots[1].id, 'G4 an explicit root id wins')
  ok(splitRootToken('@1/kb/shared.md') === 'kb/shared.md', 'G5 the selection token splits back to the path')
  ok(parseRootToken('@0/kb/x.md').rootIndex === 0, 'G6 the parser keeps the root index')

  // ---- parity: the SAME declaration bytes read by the engine resolver ----
  const checkParity = (fixture, label) => {
    const ts = resolutionOf(fixture)
    const py = pythonFace(fixture.key)
    if (ts.state === 'served') {
      ok(py.state === 'served' && py.source === ts.source, `${label}: source agrees`, JSON.stringify(py))
      ok(JSON.stringify(py.roots) === JSON.stringify(ts.roots.map((r) => r.id)),
        `${label}: root identities agree`, `${JSON.stringify(py.roots)} vs ${JSON.stringify(ts.roots.map((r) => r.id))}`)
      ok(JSON.stringify(py.root_states) === JSON.stringify(ts.roots.map((r) => r.state)),
        `${label}: root states agree`)
      ok(JSON.stringify(py.projections) === JSON.stringify(ts.projections),
        `${label}: projections agree`)
    } else {
      ok(py.state === 'refused' && py.code === ts.code,
        `${label}: refusal code agrees`, `${py.code} vs ${ts.code}`)
    }
  }
  const parityOne = project({ paths: rootsBlock([{ repository: '.', path: 'docs' }]) })
  write(parityOne.projectRoot, 'docs/a.md', FM)
  checkParity(parityOne, 'G7 declared one root')

  const parityTwo = project({ members: ['repo-b'], paths: rootsBlock([
    { repository: '.', path: 'kb' }, { repository: 'repo-b', path: 'kb', projections: 'entries,fulltext' }]) })
  mkdirSync(join(parityTwo.projectRoot, 'kb'), { recursive: true })
  mkdirSync(join(parityTwo.projectRoot, 'repo-b', 'kb'), { recursive: true })
  checkParity(parityTwo, 'G8 declared many roots + projections')

  const parityImplied = project()
  write(parityImplied.projectRoot, 'docs/a.md', FM)
  checkParity(parityImplied, 'G9 implied default root')

  const parityAbsent = project()
  checkParity(parityAbsent, 'G10 undeclared and no docs/')

  const parityMoved = project({ paths: rootsBlock([{ repository: '.', path: 'gone' }]) })
  checkParity(parityMoved, 'G11 declared root absent')

  const parityMalformed = project({ paths: '  docs_roots:\n    - repository: .\n      path: /etc\n' })
  checkParity(parityMalformed, 'G12 malformed declaration')
}

for (const d of tmpDirs) rmSync(d, { recursive: true, force: true })
console.log(`\nT261103_12_DOCS_ROOTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
