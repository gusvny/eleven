/**
 * Baseline: the epic (立项单) API contract, group 2 — the docs/epics face.
 *
 * Intent: the epics API is the read face of the epic registry. This baseline locks the
 * contract so that a route regression (escape guard broken, silent failure, a badge
 * that lies) is caught mechanically rather than by accident.
 *
 * t261030-30 migrated this baseline to the store the engine reads:
 *   - the directory is <project root>/docs/epics (env SANDBAR_EPICS_DIR wins when it is
 *     set and non-empty); notes/epics is not read at all;
 *   - a row comes from the document's front-matter record (code / retired / summary /
 *     started), and the legacy field table is only a fallback;
 *   - the close/status write routes are gone (410, t261019-12): retiring an epic is an
 *     edit of `retired:` in git.
 *
 * Steps (fully offline: tmp fixture + stub admin.py + mock HTTP):
 *   A. listEpics over a fixture directory: legal *.md files become rows sorted by code;
 *      an illegal code shape and a non-md file are not rows; a document without
 *      front-matter degrades with a named defect and keeps the legacy status line; an
 *      absent directory throws a named error (never an empty registry that reads as
 *      "this project has no epic"). A2 pins the anchor rule.
 *   B. detail route: 200 carries the front-matter row + path; illegal shape -> 400
 *      (every shape); double-encoded traversal -> 4xx; 404 names the existing codes;
 *      POST -> 405; unknown subpath -> 404; list route -> 200 with the count.
 *   C. /tickets aggregation: status buckets + row fields; two degraded paths
 *      (admin.py crash and ok:false) -> 200 degraded, never 502.
 *   D. the retired write face: close/status answer 410 with a message that points at
 *      docs/epics/<code>.md, and the document on disk is untouched.
 *
 * Reference implementation: server/plugins/workbench/smoke/epics.mjs (that smoke file
 * still pins the pre-t261019-12 notes/epics face; it is outside this ticket's write set).
 */

import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { EPIC_CODE_RE, listEpics, resolveEpicsDir } from './../src/host/epics.ts'
import { apply } from './../node.ts'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const EPIC_MD = `---
code: demo-epic
retired: false
summary: Demonstrate the registry contract.
started: 2026-08-25
---

# demo-epic

## Goal

Show the shape.
`

const RETIRED_MD = `---
code: aaa
retired: true
summary: A retired epic.
started: 2026-08-01
---

# aaa
`

const LEGACY_MD = `# 立项单：legacy-epic

| 字段 | 值 |
| --- | --- |
| 代号 | \`legacy-epic\` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-08-25 |
`

const tmp = await mkdtemp(join(tmpdir(), 'integ-epics-api-'))
const savedEnv = { SANDBAR_EPICS_DIR: process.env.SANDBAR_EPICS_DIR }

/** mock webServer/req/res 支架（与 workbench smoke 测试同模式）。 */
function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  const find = (kind, path) => routes.find(r => r.kind === kind && r.path === path)
  return {
    exactEpics: find('exact', '/sandbar-workbench/api/epics'),
    prefixEpics: find('prefix', '/sandbar-workbench/api/epics'),
    exactTickets: find('exact', '/sandbar-workbench/api/wf/tickets'),
  }
}
const mockRes = () => ({
  status: 0, body: null,
  writeHead(s) { this.status = s },
  end(b) { this.body = b ? JSON.parse(b) : null },
})
const call = async (handler, url, method = 'GET', bodyObj) => {
  const res = mockRes()
  const payload = bodyObj === undefined ? [] : [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* payload } }
  await handler.handler(req, res)
  return res
}

/** 桩 admin.py：ticket list / workflow list / ticket create（ok 可配）。 */
async function writeStub(repo, { createOk = true } = {}) {
  await mkdir(join(repo, 'server'), { recursive: true })
  await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"count": 2, "tickets": [
        {"id": "t260831-01", "title": "closed ticket", "status": "closed", "stage": "settled", "stage_state": "done", "epic": "demo-epic"},
        {"id": "t260831-02", "title": "open ticket", "status": "dispatched", "stage": "implement", "stage_state": "running", "epic": "demo-epic"}
    ]}}))
    sys.exit(0)
if tool == 'workflow' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"workflows": [{"id": "dev-lane", "name": "dev"}]}}))
    sys.exit(0)
if tool == 'ticket' and args.get('op') == 'create':
    ${createOk ? 'print(json.dumps({"ok": True, "result": {"id": "t-new"}}))' : 'print(json.dumps({"ok": False, "error": "stub create failed"})); sys.exit(1)'}
    sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')
}

try {
  /* ------------------------------------------------------------ A. list + anchor */
  section('A epics list / anchor / record degradation')
  const epicsDir = join(tmp, 'docs', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'demo-epic.md'), EPIC_MD, 'utf8')
  await writeFile(join(epicsDir, 'aaa.md'), RETIRED_MD, 'utf8')
  await writeFile(join(epicsDir, 'legacy-epic.md'), LEGACY_MD, 'utf8')
  await writeFile(join(epicsDir, 'README.md'), '# notes\n', 'utf8')     // illegal shape: not a row
  await writeFile(join(epicsDir, 'notes.txt'), 'not a charter\n', 'utf8') // non-md: not a row
  const list = await listEpics(epicsDir)
  ok(list.length === 3 && list[0].code === 'aaa' && list[1].code === 'demo-epic' && list[2].code === 'legacy-epic',
    'only valid *.md collected, sorted by code')
  const demo = list.find((e) => e.code === 'demo-epic')
  ok(demo.retired === false && demo.summary === 'Demonstrate the registry contract.'
    && demo.started === '2026-08-25' && demo.status === 'open' && demo.defect === undefined,
    'front-matter row: retired/summary/started/status=open, no defect')
  const retiredRow = list.find((e) => e.code === 'aaa')
  ok(retiredRow.retired === true && retiredRow.status === 'retired', 'retired: true reads as retired')
  const legacyRow = list.find((e) => e.code === 'legacy-epic')
  ok(legacyRow.status === '已立项（执行中）' && String(legacyRow.defect).includes('no front-matter block')
    && legacyRow.retired === true,
    'document without front-matter: legacy table status + named defect + fail-closed retired')
  ok(list.every((e) => typeof e.status === 'string' && e.status !== ''), 'no row carries a blank status')
  let threw = ''
  try { await listEpics(join(tmp, 'no-such-dir')) } catch (e) { threw = String(e && e.message) }
  ok(threw.includes('epic registry directory not found') && threw.includes('docs/epics'),
    'missing dir -> named error naming docs/epics (no empty registry pretending "no epic")')
  ok(EPIC_CODE_RE.test('demo-epic') && !EPIC_CODE_RE.test('..%2f..%2fetc'), 'EPIC_CODE_RE whitelist shape')

  section('A2 the anchor rule (env when non-empty, else <root>/docs/epics)')
  delete process.env.SANDBAR_EPICS_DIR
  ok(resolveEpicsDir('/some/repo') === join('/some/repo', 'docs', 'epics'), 'no env -> <root>/docs/epics')
  process.env.SANDBAR_EPICS_DIR = ''
  ok(resolveEpicsDir('/some/repo') === join('/some/repo', 'docs', 'epics'), 'empty env is not an anchor')
  process.env.SANDBAR_EPICS_DIR = '/env/epics'
  ok(resolveEpicsDir('/some/repo') === '/env/epics', 'non-empty env wins')

  /* ------------------------------------------------------------ B. detail + anti-traversal */
  section('B detail route + anti-traversal (shapes / encoding / 404 / 405 / unknown subpath)')
  const repoB = join(tmp, 'repo-b')
  await writeStub(repoB)
  process.env.SANDBAR_EPICS_DIR = epicsDir
  const h = makeHarness(repoB)
  ok(h.prefixEpics !== undefined && h.exactEpics !== undefined, 'epics exact+prefix routes mounted')
  let r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic')
  ok(r.status === 200 && r.body.result.path === 'docs/epics/demo-epic.md'
    && r.body.result.retired === false && r.body.result.summary === 'Demonstrate the registry contract.'
    && r.body.result.started === '2026-08-25',
    'GET detail -> 200 front-matter row + path docs/epics/<code>.md')
  r = await call(h.exactEpics, '/sandbar-workbench/api/epics')
  ok(r.status === 200 && r.body.result.count === 3, 'GET list route -> 200 count')
  for (const bad of ['Demo-epic', 'a b', 'x'.repeat(42)]) {
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/${encodeURIComponent(bad)}`)
    ok(r.status === 400, `invalid shape '${bad.slice(0, 12)}' -> 400`)
  }
  // '..' is normalized away by URL parsing; traversal shapes are sent percent-encoded
  // (the entry a real attacker would use).
  for (const enc of ['%2e%2e', '..%2f..%2fetc', '%2e%2e%2f%2e%2e%2fpasswd', 'a%2Fb']) {
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/${enc}`)
    ok(r.status >= 400 && r.status < 500, `traversal shape '${enc}' -> rejected with 4xx`)
  }
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic')
  ok(r.status === 404 && String(r.body.error).includes('not found') && String(r.body.error).includes('demo-epic'),
    'non-existent -> 404 human message listing existing codes')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic', 'POST')
  ok(r.status === 405, 'POST detail -> 405 (read-only contract)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/bogus-op')
  ok(r.status === 404, 'unknown subpath -> 404 human message')

  /* ------------------------------------------------------------ C. /tickets + degraded paths */
  section('C /tickets aggregation (buckets / row fields) + two degraded paths')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
  ok(r.status === 200 && r.body.ok === true && r.body.result.count === 2, 'GET /tickets -> 2 tickets')
  ok(r.body.result.buckets.closed === 1 && r.body.result.buckets.dispatched === 1, 'bucketed by status')
  const row = r.body.result.tickets.find(t => t.id === 't260831-02')
  ok(row !== undefined && row.stage === 'implement' && row.stage_state === 'running', 'ticket row fields present')
  // Degraded path 1: admin.py crashes (non-JSON output) -> 200 degraded, never 502.
  const repoC = join(tmp, 'repo-c')
  await mkdir(join(repoC, 'server'), { recursive: true })
  await writeFile(join(repoC, 'server', 'admin.py'),
    "import sys\nsys.stderr.write('temporal unreachable: connection refused'); sys.exit(2)\n", 'utf8')
  const hC = makeHarness(repoC)
  r = await call(hC.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
  ok(r.status === 200 && r.body.result?.degraded === true
    && String(r.body.result.reason).includes('connection refused'),
    'admin.py crash (non-JSON) -> 200 degraded, reason carries underlying error')
  // Degraded path 2: ok:false -> degraded, reason passes the underlying error through.
  await writeFile(join(repoC, 'server', 'admin.py'), `import json, sys
if sys.argv[2] == 'ticket' and json.loads(sys.argv[3]).get('op') == 'list':
    print(json.dumps({"ok": False, "error": "ticket-list failed: temporal unreachable: connection refused"})); sys.exit(1)
print(json.dumps({"ok": False, "error": "stub unsupported"})); sys.exit(1)
`, 'utf8')
  r = await call(hC.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
  ok(r.status === 200 && r.body.result?.degraded === true
    && String(r.body.result.reason).includes('connection refused'),
    'ok:false -> 200 degraded, reason passthrough of underlying error')

  /* ------------------------------------------------------------ D. retired write face */
  section('D the write face is retired: close/status answer 410 and touch no file')
  const before = await readFile(join(epicsDir, 'demo-epic.md'), 'utf8')
  for (const sub of ['close', 'status']) {
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/demo-epic/${sub}`, 'POST', { status: '已完结' })
    ok(r.status === 410 && String(r.body.error).includes('t261019-12')
      && String(r.body.error).includes('docs/epics/demo-epic.md'),
      `POST ${sub} -> 410 naming docs/epics/<code>.md (the document is edited in git now)`)
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/demo-epic/${sub}`, 'GET')
    ok(r.status === 410, `GET ${sub} -> 410 (the same named retirement)`)
  }
  const after = await readFile(join(epicsDir, 'demo-epic.md'), 'utf8')
  ok(after === before, 'the document on disk is untouched by the retired routes')

  // t260910-14 retirement note: the old section E (next-hint cache / bad JSON tolerance /
  // dismiss removal + backup + idempotence) is gone with the whole suggest_next chain.
} finally {
  // Every end state is reclaimed: restore the env, remove the tmp fixture.
  if (savedEnv.SANDBAR_EPICS_DIR === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv.SANDBAR_EPICS_DIR
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
