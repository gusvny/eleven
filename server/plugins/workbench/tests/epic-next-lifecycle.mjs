/**
 * Baseline: epic "next suggestion" lifecycle (group 3).
 *
 * Intent:
 *   The badge-off lifecycle of the epic next-suggestion chain was historically broken
 *   ("stale badge stays lit"). This baseline locks the full lifecycle: a produced
 *   suggestion surfaces as a detail hint, and is invalidated the moment a prefilled
 *   ticket is actually created — plus the stub degradation paths stay recoverable
 *   with no leaked processes.
 *
 * High-level steps (tmp repo fixture + stub admin.py + mock HTTP; zero real models,
 * zero Temporal connections):
 *   L1. suggest produces: stub job runs to done with a valid suggestion.
 *   L2. precache lands (shared.EpicNextCache schema) -> detail nextHint hit.
 *   L3. prefilled ticket created successfully -> cache deleted, badge off, backup
 *       written; negative contract: failed creation keeps the cache.
 *   L4. dismiss is idempotent (missing file is fine).
 *   V.  stub variants: invalid_json -> fail-fast with a reason naming the bad JSON;
 *       never_write -> timeout degradation; both with smoke-style process-reaping
 *       assertions (no leaked dummy agent processes).
 *
 * What "stub-driven" means: the suggest job normally spawns a real LLM agent (slow,
 * non-deterministic, costly). Setting SUYOU_EPIC_NEXT_STUB makes startSuggestJob skip
 * the agent spawn and write a canned result.json instead (variants: ok / invalid_json
 * / never_write), while keeping the polling, validation, and process-reaping paths
 * identical to production — so the whole lifecycle is exercised deterministically
 * with zero model calls.
 *
 * Reference implementation: server/plugins/workbench/smoke/epic-next.mjs. Trade-offs
 * (reviewed in create_plan): carried over — B1 stub full chain, invalid_json /
 * never_write variants, B6a/B6b process-reaping assertions (same file, same terminal
 * state); NOT carried over — concurrent jobs / cleanupOldJobs / timeout tuning
 * (fine-grained job-manager contract, already covered by the smoke); NEW here —
 * badge-off on successful prefilled creation, dismiss idempotency + backup.
 *
 * Note: the precache dir is <repo>/.suyou/epic-next by design (resolvePrecacheDir
 * ignores env; SUYOU_EPIC_NEXT_DIR only isolates job dirs).
 */

import { spawnSync } from 'node:child_process'
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { apply } from './../node.ts'
import {
  dismissPrecache, precacheExists, startSuggestJob, pollSuggestJob, stateKeyFromRows,
} from './../src/host/epic-next.ts'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = await mkdtemp(join(tmpdir(), 'integ-epic-next-lifecycle-'))
const repo = join(tmp, 'repo')
const epicsDir = join(repo, 'notes', 'epics')
const jobsDir = join(tmp, 'jobs')
const savedEnv = {
  SUYOU_EPIC_NEXT_DIR: process.env.SUYOU_EPIC_NEXT_DIR,
  SUYOU_EPIC_NEXT_STUB: process.env.SUYOU_EPIC_NEXT_STUB,
  SUYOU_EPIC_NEXT_TIMEOUT_MS: process.env.SUYOU_EPIC_NEXT_TIMEOUT_MS,
  SUYOU_EPICS_DIR: process.env.SUYOU_EPICS_DIR,
  SUYOU_PROJECTS_YAML: process.env.SUYOU_PROJECTS_YAML,
}
const stubPids = []
const alive = (pid) => { try { process.kill(pid, 0); return true } catch { return false } }
const killTree = (pid) => {
  try { process.kill(-pid, 'SIGKILL') } catch { try { process.kill(pid, 'SIGKILL') } catch { /* already dead */ } }
}

/** Stub admin.py: ticket list (one closed row) / workflow list / ticket create (ok configurable). */
async function writeStub(repoDir, { createOk = true } = {}) {
  await mkdir(join(repoDir, 'server'), { recursive: true })
  await writeFile(join(repoDir, 'server', 'admin.py'), `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"count": 1, "tickets": [
        {"id": "t260831-90", "title": "closed ticket", "status": "closed", "stage": "settled", "stage_state": "done", "epic": "demo-epic"}]}}))
    sys.exit(0)
if tool == 'workflow' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"workflows": [{"id": "dev-lane", "name": "dev"}]}}))
    sys.exit(0)
if tool == 'ticket' and args.get('op') == 'create':
    ${createOk ? 'print(json.dumps({"ok": True, "result": {"id": "t-new", "epic": args.get("epic") or ""}}))' : 'print(json.dumps({"ok": False, "error": "stub create failed"})); sys.exit(1)'}
    sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')
}

function makeHarness(repoDir) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  apply({
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }, { repo: repoDir })
  return {
    prefixEpics: routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/epics'),
    exactTickets: routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/wf/tickets'),
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

/** Poll a job to terminal state (100ms steps, 5s cap). */
async function pollUntilDone(jobId) {
  let job = null
  for (let i = 0; i < 50; i++) {
    job = await pollSuggestJob(jobId)
    if (job && job.state !== 'running') return job
    await new Promise(r => setTimeout(r, 100))
  }
  return job
}

/** Land the precache the python side would write (schema mirrors shared.EpicNextCache:
 *  epic + state_key + suggestion). */
async function writePrecache(repoDir, code, rows, suggestion) {
  const dir = join(repoDir, '.suyou', 'epic-next', code)
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, 'pre.json'), JSON.stringify({
    epic: code, state_key: stateKeyFromRows(rows, ''), suggestion,
  }), 'utf8')
}

try {
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'demo-epic.md'),
    '# 立项单：demo-epic\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `demo-epic` |\n| 状态 | 已立项（执行中） |\n', 'utf8')
  await writeStub(repo, { createOk: true })
  // Project registry (POST /wf/tickets ?project= whitelist) pointed at tmp
  await writeFile(join(tmp, 'projects.yaml'),
    `projects:\n  - key: suyou\n    name: 溯游\n    dirs:\n      - ${repo}\n`, 'utf8')
  process.env.SUYOU_EPICS_DIR = epicsDir
  process.env.SUYOU_EPIC_NEXT_DIR = jobsDir
  process.env.SUYOU_PROJECTS_YAML = join(tmp, 'projects.yaml')
  process.env.SUYOU_EPIC_NEXT_TIMEOUT_MS = '5000'
  const { exactTickets, prefixEpics } = makeHarness(repo)
  const cacheDir = join(repo, '.suyou', 'epic-next')
  const rows = [{ id: 't260831-90', closed: true }]

  /* ------------------------------------------------ L1 suggest produces (STUB=ok) */
  section('L1 suggest produces (SUYOU_EPIC_NEXT_STUB=ok)')
  process.env.SUYOU_EPIC_NEXT_STUB = 'ok'
  const job = await startSuggestJob({
    repo, code: 'demo-epic', epicTitle: 'demo-epic',
    epicMarkdown: await readFile(join(epicsDir, 'demo-epic.md'), 'utf8'),
    ticketsSummary: '(1 closed ticket)', workflows: [{ id: 'dev-lane', name: 'dev' }],
  })
  if (job.proc?.pid) stubPids.push(job.proc.pid)
  const done = await pollUntilDone(job.jobId)
  ok(done?.state === 'done' && done.suggestion?.workflow === 'dev-lane' && done.suggestion.title !== '',
    'stub suggest job -> done with a valid suggestion (template whitelisted, title non-empty)')

  /* ------------------------------------------------ L2 precache lands -> nextHint hit */
  section('L2 precache lands -> detail nextHint hit')
  await writePrecache(repo, 'demo-epic', rows, {
    workflow: 'dev-lane', title: 'next ticket: lifecycle tests',
    body: 'prefilled body', rationale: 'prefilled rationale',
    write_set: ['integration/manifest.json'],
  })
  ok(await precacheExists(cacheDir, 'demo-epic') === true, 'precache landed -> list badge lit (precacheExists)')
  let r = await call(prefixEpics, '/sandbar-workbench/api/epics/demo-epic')
  ok(r.status === 200 && r.body.result?.nextHint?.status === 'ok'
    && String(r.body.result.nextHint.title).includes('next ticket'),
    'GET detail -> nextHint hit (state_key aligned + template whitelist passed)')

  /* ------------------------------------------------ L3 successful prefilled creation -> cache deleted */
  section('L3 prefilled ticket created -> cache invalidated (node.ts:306 dismiss on ok)')
  r = await call(exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', {
    workflow: 'dev-lane', title: 'prefilled creation (integration baseline)',
    body: 'prefilled body', epic: 'demo-epic', write_set: ['integration/manifest.json'],
  })
  ok(r.status === 200 && r.body.ok === true, 'prefilled creation -> 200 ok (stub admin.py create allows)')
  ok(existsSync(join(cacheDir, 'demo-epic', 'pre.json')) === false, 'creation ok -> precache deleted (state_key already stale, no lying badge)')
  ok(await precacheExists(cacheDir, 'demo-epic') === false, 'badge off (precacheExists=false)')
  const hintBackups = existsSync('/tmp/epic-next-backup') ? await readdir('/tmp/epic-next-backup') : []
  ok(hintBackups.some(f => f.startsWith('demo-epic-')), 'backup written to /tmp/epic-next-backup before deleting')
  // Reverse contract: failed creation keeps the cache (no wrongful invalidation)
  const repoF = join(tmp, 'repo-fail')
  await mkdir(join(repoF, 'notes', 'epics'), { recursive: true })
  await writeFile(join(repoF, 'notes', 'epics', 'demo-epic.md'), '# 立项单：demo-epic\n\n| 状态 | 已立项 |\n', 'utf8')
  await writeStub(repoF, { createOk: false })
  const { exactTickets: ft } = makeHarness(repoF)
  await writePrecache(repoF, 'demo-epic', rows, { workflow: 'dev-lane', title: 't', body: '', rationale: '' })
  r = await call(ft, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', {
    workflow: 'dev-lane', title: 'should fail', epic: 'demo-epic',
  })
  ok(r.status === 200 && r.body.ok === false, 'failed creation -> 200 structured ok:false passthrough')
  ok(await precacheExists(join(repoF, '.suyou', 'epic-next'), 'demo-epic') === true,
    'failed creation -> cache kept (best-effort invalidation only on ok:true)')

  /* ------------------------------------------------ L4 dismiss idempotency */
  section('L4 dismiss idempotency')
  const dr1 = await dismissPrecache(cacheDir, 'demo-epic')
  ok(dr1.ok === true, 'dismiss (cache already gone) -> ok (idempotent first strike)')
  const dr2 = await dismissPrecache(cacheDir, 'demo-epic')
  ok(dr2.ok === true, 'second dismiss -> still ok (idempotent, repeated clicks never error)')

  /* ------------------------------------------------ V stub variants + process reaping (smoke B6) */
  section('V stub variant degradation + full-terminal-state process reaping (smoke B6a/B6b discipline)')
  process.env.SUYOU_EPIC_NEXT_STUB = 'invalid_json'
  const jBad = await startSuggestJob({
    repo, code: 'demo-epic', epicTitle: 'demo-epic', epicMarkdown: 'md',
    ticketsSummary: '-', workflows: [{ id: 'dev-lane', name: 'dev' }],
  })
  if (jBad.proc?.pid) stubPids.push(jBad.proc.pid)
  const badDone = await pollUntilDone(jBad.jobId)
  ok(badDone?.state === 'failed' && String(badDone.reason).includes('合法 JSON'),
    'invalid_json variant -> fail-fast, reason names the invalid JSON result file')
  ok(jBad.proc?.killed === true || !alive(jBad.proc?.pid ?? 0),
    'invalid_json variant: dummy process reaped (killed/not alive, smoke B6a assertion)')

  process.env.SUYOU_EPIC_NEXT_STUB = 'never_write'
  process.env.SUYOU_EPIC_NEXT_TIMEOUT_MS = '300'
  const jStall = await startSuggestJob({
    repo, code: 'demo-epic', epicTitle: 'demo-epic', epicMarkdown: 'md',
    ticketsSummary: '-', workflows: [{ id: 'dev-lane', name: 'dev' }],
  })
  if (jStall.proc?.pid) stubPids.push(jStall.proc.pid)
  const stallDone = await pollUntilDone(jStall.jobId)
  ok(stallDone?.state === 'failed' && String(stallDone.reason).includes('未产出结果'),
    'never_write variant -> timeout degradation, reason names the missing result (retryable)')
  await new Promise(r => setTimeout(r, 3500)) // let reap's TERM -> 3s -> KILL grace finish
  ok(jStall.proc?.killed === true || !alive(jStall.proc?.pid ?? 0),
    'never_write variant: timeout fallback reaps the dummy process (smoke B6b assertion)')
} finally {
  // Full-terminal-state cleanup: kill stub dummy processes, restore env, rm tmp fixtures
  for (const pid of stubPids) killTree(pid)
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) delete process.env[k]
    else process.env[k] = v
  }
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
