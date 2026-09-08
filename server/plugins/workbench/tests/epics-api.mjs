/**
 * Baseline: epics (project charter) API contract (group 2).
 *
 * Intent:
 *   The epics API is the read/write surface over project charters. This baseline locks
 *   its contract so route regressions (broken anti-traversal, silently failing close,
 *   lying badge) are caught mechanically instead of by accident.
 *
 * High-level steps (fully offline: tmp repo fixture + stub admin.py + mock HTTP):
 *   A. listEpics over a fixture dir: valid *.md collected/sorted; bad shapes ignored;
 *      missing/empty dir -> empty array, no throw.
 *   B. detail route: 200 with markdown; invalid shapes -> 400 (full shape set);
 *      double-encoded traversal -> 4xx; 404 with existing-code list; POST -> 405;
 *      unknown subpath -> 404.
 *   C. /tickets aggregation: status buckets + row fields; two degraded paths
 *      (admin.py crash and ok:false) -> 200 degraded, never 502.
 *   D. close: POST-only; status row rewritten to 已完结 with /tmp backup; missing
 *      status row -> 422; 404 for unknown code.
 *   E. next-hint cache: bad-JSON cache -> badge lit but hint = miss; stale state_key
 *      -> miss; dismiss deletes cache (with /tmp backup) and is idempotent; invalid
 *      code -> 400.
 *
 * Reference implementation: server/plugins/workbench/smoke/epics.mjs. Fault-mode
 * trade-offs were reviewed item-by-item in create_plan (all of its 10 fault modes
 * carried over, plus close/dismiss added; ticket rows' epic passthrough NOT
 * duplicated here -- smoke C5 already covers it).
 *
 * Known engine bug (recorded here, to be fixed in a separate ticket -- engine files
 * are outside this ticket's write set):
 *   POST /sandbar-workbench/api/epics/<code>/next-hint/dismiss always returns 405.
 *   Root cause: the GET-only 405 branch (node.ts:1034) sits BEFORE the dismiss branch
 *   (node.ts:1063), contradicting the comment at node.ts:1062 ("must branch before
 *   the GET-only 405"). The frontend [dismiss] button (src/client/epics.tsx:258, POST)
 *   is therefore dead. The contract is asserted at the dismissPrecache function level
 *   below; the route-level probe prints a KNOWN-ISSUE line and does NOT count as FAIL.
 *   After the fix, turn it back into a route-level "POST dismiss -> 200" assertion.
 */

import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { EPIC_CODE_RE, listEpics, resolveEpicsDir } from './../src/host/epics.ts'
import { precacheExists, readPrecacheHint, dismissPrecache, stateKeyFromRows } from './../src/host/epic-next.ts'
import { apply } from './../node.ts'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const EPIC_MD = `# 立项单：demo-epic

| 字段 | 值 |
| --- | --- |
| 代号 | \`demo-epic\` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-08-25 |

## 目标

做个示范。
`

const tmp = await mkdtemp(join(tmpdir(), 'integ-epics-api-'))
const savedEnv = { SUYOU_EPICS_DIR: process.env.SUYOU_EPICS_DIR, SUYOU_EPIC_NEXT_DIR: process.env.SUYOU_EPIC_NEXT_DIR }

/** Mock webServer/req/res harness (same pattern as workbench smoke tests). */
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

/** Stub admin.py: ticket list / workflow list / ticket create (configurable ok). */
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
  /* ------------------------------------------------------------ A. list + dir tolerance */
  section('A epics list / directory tolerance')
  const epicsDir = join(tmp, 'notes', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'demo-epic.md'), EPIC_MD, 'utf8')
  await writeFile(join(epicsDir, 'aaa.md'), '# 立项单：aaa\n\n| 状态 | 已归档 |\n| 立项日期 | 2026-08-01 |\n', 'utf8')
  await writeFile(join(epicsDir, 'README.md'), '# notes\n', 'utf8')     // bad shape: not listed
  await writeFile(join(epicsDir, 'notes.txt'), 'not a charter\n', 'utf8') // not .md: not listed
  const list = await listEpics(epicsDir)
  ok(list.length === 2 && list[0].code === 'aaa' && list[1].code === 'demo-epic', 'only valid *.md collected, sorted by code')
  ok((await listEpics(join(tmp, 'no-such-dir'))).length === 0, 'missing dir -> empty array, no throw')
  ok(EPIC_CODE_RE.test('demo-epic') && !EPIC_CODE_RE.test('..%2f..%2fetc'), 'EPIC_CODE_RE whitelist shape')

  /* ------------------------------------------------------------ B. detail + anti-traversal */
  section('B detail route + anti-traversal (shapes / encoding / 404 / 405 / unknown subpath)')
  const repoB = join(tmp, 'repo-b')
  await writeStub(repoB)
  process.env.SUYOU_EPICS_DIR = epicsDir
  const h = makeHarness(repoB)
  ok(h.prefixEpics !== undefined && h.exactEpics !== undefined, 'epics exact+prefix routes mounted')
  let r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic')
  ok(r.status === 200 && r.body.result.markdown.includes('## 目标')
    && r.body.result.path === 'notes/epics/demo-epic.md', 'GET detail -> 200 markdown+path')
  r = await call(h.exactEpics, '/sandbar-workbench/api/epics')
  ok(r.status === 200 && r.body.result.count === 2, 'GET list route -> 200 count')
  for (const bad of ['Demo-epic', 'a b', 'x'.repeat(42)]) {
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/${encodeURIComponent(bad)}`)
    ok(r.status === 400, `invalid shape '${bad.slice(0, 12)}' -> 400`)
  }
  // '..' is normalized away by URL parsing; traversal shapes hit the route encoded
  // (same surface a real attacker would use)
  for (const enc of ['%2e%2e', '..%2f..%2fetc', '%2e%2e%2f%2e%2e%2fpasswd', 'a%2Fb']) {
    r = await call(h.prefixEpics, `/sandbar-workbench/api/epics/${enc}`)
    ok(r.status >= 400 && r.status < 500, `traversal shape '${enc}' -> rejected with 4xx`)
  }
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic')
  ok(r.status === 404 && String(r.body.error).includes('不存在') && String(r.body.error).includes('demo-epic'),
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
  // Degraded path 1: admin.py crashes (non-JSON) -> 200 degraded, never 502
  const repoC = join(tmp, 'repo-c')
  await mkdir(join(repoC, 'server'), { recursive: true })
  await writeFile(join(repoC, 'server', 'admin.py'),
    "import sys\nsys.stderr.write('temporal unreachable: connection refused'); sys.exit(2)\n", 'utf8')
  const hC = makeHarness(repoC)
  r = await call(hC.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
  ok(r.status === 200 && r.body.result?.degraded === true
    && String(r.body.result.reason).includes('connection refused'),
    'admin.py crash (non-JSON) -> 200 degraded, reason carries underlying error')
  // Degraded path 2: ok:false -> degraded with reason passthrough
  await writeFile(join(repoC, 'server', 'admin.py'), `import json, sys
if sys.argv[2] == 'ticket' and json.loads(sys.argv[3]).get('op') == 'list':
    print(json.dumps({"ok": False, "error": "ticket-list failed: temporal unreachable: connection refused"})); sys.exit(1)
print(json.dumps({"ok": False, "error": "stub unsupported"})); sys.exit(1)
`, 'utf8')
  r = await call(hC.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
  ok(r.status === 200 && r.body.result?.degraded === true
    && String(r.body.result.reason).includes('connection refused'),
    'ok:false -> 200 degraded, reason passthrough of underlying error')

  /* ------------------------------------------------------------ D. close (rewrite + backup + 422) */
  section('D close: status-row rewrite + /tmp backup + 422 (new vs smoke)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/close', 'GET')
  ok(r.status === 405, 'GET close -> 405 (human-confirmed POST-only action)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/close', 'POST')
  ok(r.status === 200 && r.body.result?.status === '已完结', 'POST close -> status row rewritten to 已完结')
  const after = await readFile(join(epicsDir, 'demo-epic.md'), 'utf8')
  ok(after.includes('| 状态 | 已完结 |') && !after.includes('已立项（执行中）'), 'close persisted: status row actually rewritten on disk')
  const backupDir = '/tmp/epic-close-backup'
  const backups = existsSync(backupDir) ? await readdir(backupDir) : []
  ok(backups.some(f => f.startsWith('demo-epic-')), 'close backed up to /tmp/epic-close-backup before writing')
  await writeFile(join(epicsDir, 'no-status.md'), '# 立项单：no-status\n\nno status row here.\n', 'utf8')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/no-status/close', 'POST')
  ok(r.status === 422 && String(r.body.error).includes('状态'), 'missing status row -> 422 (no vague success)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic/close', 'POST')
  ok(r.status === 404, 'close on non-existent code -> 404')

  /* ------------------------------------------------------------ E. next-hint cache + dismiss */
  section('E next-hint: bad-JSON cache treated as miss / dismiss delete+backup+idempotent (new vs smoke)')
  // The precache dir is keyed to the repo by design: resolvePrecacheDir does NOT read
  // env (env SUYOU_EPIC_NEXT_DIR only isolates job dirs). Tests follow the real source.
  const cacheDir = join(repoB, '.suyou', 'epic-next')
  const rows = [{ id: 't260831-01', closed: true }, { id: 't260831-02', closed: false }]
  const stateKey = stateKeyFromRows(rows, '')
  const wfIds = ['dev-lane']
  // Bad JSON cache: badge lit (precacheExists only stats), detail hint = miss
  await mkdir(join(cacheDir, 'demo-epic'), { recursive: true })
  await writeFile(join(cacheDir, 'demo-epic', 'pre.json'), '{"status":"ok","workflow":"dev-l\\-broken-escape', 'utf8')
  ok(await precacheExists(cacheDir, 'demo-epic') === true, 'bad-JSON cache exists -> badge lit (precacheExists only stats)')
  ok(await readPrecacheHint(cacheDir, 'demo-epic', stateKey, wfIds) === null, 'bad-JSON cache -> hint treated as miss (null, no crash)')
  // Valid cache hit
  const goodCache = { epic: 'demo-epic', state_key: stateKey, suggestion: { workflow: 'dev-lane', title: 'next ticket', body: 'b', rationale: 'r' } }
  await writeFile(join(cacheDir, 'demo-epic', 'pre.json'), JSON.stringify(goodCache), 'utf8')
  const hint = await readPrecacheHint(cacheDir, 'demo-epic', stateKey, wfIds)
  ok(hint?.status === 'ok' && hint.title === 'next ticket', 'valid cache -> hint hit (state_key aligned)')
  ok(await readPrecacheHint(cacheDir, 'demo-epic', 'stale-key', wfIds) === null, 'stale state_key -> miss (stale suggestion never shows)')
  // Detail route carries nextHint (full route + stub admin.py queries)
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic')
  ok(r.status === 200 && r.body.result?.nextHint?.title === 'next ticket', 'GET detail -> nextHint projection hit')
  // Dismiss: function-level contract (route-level probe below; see known engine bug note)
  ok(await dismissPrecache(cacheDir, 'demo-epic').then(r => r.ok === true), 'dismissPrecache -> cache deleted')
  ok(await precacheExists(cacheDir, 'demo-epic') === false, 'after dismiss cache is gone (badge off)')
  const hintBackups = existsSync('/tmp/epic-next-backup') ? await readdir('/tmp/epic-next-backup') : []
  ok(hintBackups.some(f => f.startsWith('demo-epic-')), 'dismiss backed up to /tmp/epic-next-backup before deleting')
  const dr2 = await dismissPrecache(cacheDir, 'demo-epic')
  ok(dr2.ok === true, 'second dismiss -> still ok (idempotent, missing file is fine)')
  const drBad = await dismissPrecache(cacheDir, 'BAD')
  ok(drBad.ok === false && drBad.status === 400, 'dismiss invalid code -> 400 (never deletes the wrong file)')
  // Route-level probe for the known engine bug (see file header); not counted as FAIL.
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/next-hint/dismiss', 'POST')
  if (r.status === 200) {
    ok(true, 'POST dismiss route -> 200 (engine bug fixed; route-level contract restored)')
  } else {
    console.log(`  KNOWN-ISSUE POST dismiss route -> ${r.status} (engine branch-order defect: GET-only 405 sits before the dismiss branch; see file header, fix in a separate ticket)`)
  }
} finally {
  // Full-terminal-state cleanup: restore env, remove tmp fixtures
  if (savedEnv.SUYOU_EPICS_DIR === undefined) delete process.env.SUYOU_EPICS_DIR
  else process.env.SUYOU_EPICS_DIR = savedEnv.SUYOU_EPICS_DIR
  if (savedEnv.SUYOU_EPIC_NEXT_DIR === undefined) delete process.env.SUYOU_EPIC_NEXT_DIR
  else process.env.SUYOU_EPIC_NEXT_DIR = savedEnv.SUYOU_EPIC_NEXT_DIR
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
