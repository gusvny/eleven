/**
 * 基线：立项「下一步建议」全生命周期（第 3 组）。
 *
 * 意图：
 *   立项建议链的徽标消除生命周期曾经坏过（「陈旧徽标常亮」）。本基线锁定全
 *   生命周期：产出的建议浮为详情提示，预填票真正建出那一刻缓存即失效——
 *   外加 stub 降级路径可恢复、不留泄漏进程。
 *
 * 步骤（tmp 仓 fixture + 桩 admin.py + mock HTTP；零真模型、零 Temporal 连接）：
 *   L1. 建议产出：stub job 跑到 done，建议合法。
 *   L2. 预缓存落盘（shared.EpicNextCache schema）→ 详情 nextHint 命中。
 *   L3. 预填票建出成功 → 缓存删除、徽标灭、有备份；负向契约：建票失败保留缓存。
 *   L4. dismiss 幂等（文件缺失也算成功）。
 *   V.  stub 变体：invalid_json → fail-fast 且 reason 点名坏 JSON；never_write →
 *       超时降级；两者都带 smoke 同款进程回收断言（无泄漏 dummy agent 进程）。
 *
 * 「stub 驱动」是什么：建议 job 平时会 spawn 真 LLM agent（慢、不确定、贵）。
 * 设 SANDBAR_EPIC_NEXT_STUB 后 startSuggestJob 跳过 agent spawn，改写一份预制
 * result.json（变体：ok / invalid_json / never_write），轮询、校验、进程回收
 * 路径与生产完全一致——整个生命周期确定性可测、零模型调用。
 *
 * 参考实现：server/plugins/workbench/smoke/epic-next.mjs。取舍（方案过审）：
 * 带——B1 stub 全链、invalid_json / never_write 变体、B6a/B6b 进程回收断言
 * （同文件、同终态）；不带——并发 job / cleanupOldJobs / 超时调参（细粒度
 * job-manager 契约，smoke 已覆盖）；本基线新增——预填票建出成功即灭徽标、
 * dismiss 幂等 + 备份。
 *
 * 注意：预缓存目录按设计为 <repo>/.suyou/epic-next（resolvePrecacheDir 不读
 * env；SANDBAR_EPIC_NEXT_DIR 只隔离 job 目录）。
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
  SANDBAR_EPIC_NEXT_DIR: process.env.SANDBAR_EPIC_NEXT_DIR,
  SANDBAR_EPIC_NEXT_STUB: process.env.SANDBAR_EPIC_NEXT_STUB,
  SANDBAR_EPIC_NEXT_TIMEOUT_MS: process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS,
  SANDBAR_EPICS_DIR: process.env.SANDBAR_EPICS_DIR,
  SANDBAR_PROJECTS_YAML: process.env.SANDBAR_PROJECTS_YAML,
}
const stubPids = []
const alive = (pid) => { try { process.kill(pid, 0); return true } catch { return false } }
const killTree = (pid) => {
  try { process.kill(-pid, 'SIGKILL') } catch { try { process.kill(pid, 'SIGKILL') } catch { /* already dead */ } }
}

/** 桩 admin.py：ticket list（一行 closed）/ workflow list / ticket create（ok 可配）。 */
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

/** 轮询 job 到终态（100ms 步进，5s 封顶）。 */
async function pollUntilDone(jobId) {
  let job = null
  for (let i = 0; i < 50; i++) {
    job = await pollSuggestJob(jobId)
    if (job && job.state !== 'running') return job
    await new Promise(r => setTimeout(r, 100))
  }
  return job
}

/** 落一份 python 侧会写的预缓存（schema 对齐 shared.EpicNextCache：
 *  epic + state_key + suggestion）。 */
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
  // 项目注册表（POST /wf/tickets ?project= 白名单）指向 tmp
  await writeFile(join(tmp, 'projects.yaml'),
    `projects:\n  - key: suyou\n    name: 溯游\n    dirs:\n      - ${repo}\n`, 'utf8')
  process.env.SANDBAR_EPICS_DIR = epicsDir
  process.env.SANDBAR_EPIC_NEXT_DIR = jobsDir
  process.env.SANDBAR_PROJECTS_YAML = join(tmp, 'projects.yaml')
  process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS = '5000'
  const { exactTickets, prefixEpics } = makeHarness(repo)
  const cacheDir = join(repo, '.suyou', 'epic-next')
  const rows = [{ id: 't260831-90', closed: true }]

  /* ------------------------------------------------ L1 suggest produces (STUB=ok) */
  section('L1 suggest produces (SANDBAR_EPIC_NEXT_STUB=ok)')
  process.env.SANDBAR_EPIC_NEXT_STUB = 'ok'
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
  process.env.SANDBAR_EPIC_NEXT_STUB = 'invalid_json'
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

  process.env.SANDBAR_EPIC_NEXT_STUB = 'never_write'
  process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS = '300'
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
  // 终态全回收：杀 stub dummy 进程、还原 env、删 tmp fixture
  for (const pid of stubPids) killTree(pid)
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) delete process.env[k]
    else process.env[k] = v
  }
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
