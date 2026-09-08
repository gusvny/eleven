/**
 * Scene library for the ticket-lifecycle E2E baseline (group 5).
 *
 * What is real here (per the ticket contract): the Docker test Temporal (17233 /
 * namespace suyou-test), a real per-ticket worker (worker.py on the dedicated  // naming-compat
 * task queue with WATCH self-exit), the real engine chain (prepare_workspace ->
 * create_plan <-> review_plan -> implement || design_integration_tests ->
 * run_integration_tests -> arbitrate -> acceptance_walkthrough -> merge_check ->
 * merge [human gate] -> suggest_next inline -> status=closed), real settle/merge/
 * lane cleanup and real human signals via client.py.
 *
 * What is stubbed: only the agent brains (SANDBAR_AGENT_STUB=1 stages self-complete,
 * SANDBAR_SUGGEST_STUB=ok, zero model calls).
 *
 * Isolation (merge activity lands on the worker-side REPO_ROOT current branch and
 * ignores base_ref, agent_activities.py merge()): every scene runs against a
 * disposable "fixture repo" -- a --depth 1 clone of the local main branch. The
 * worker is started from the fixture's own engine so its REPO_ROOT is the
 * fixture: lane worktrees, settles, merges and lane cleanup all happen inside the
 * fixture; the real repo is never touched.
 *
 * Determinism lever: agent activities return the cached lane result file when it
 * already exists (agent_activities.py idempotent-cache path). Scenes pre-seed
 * `.suyou/stage_arbitrate_gen<N>.json` (summary with verdict=pass) while the  // naming-compat
 * ticket is mechanically busy in run_integration_tests -- the stub brain alone
 * never emits verdict=, which is itself scene D's round-limit trigger.
 *
 * Safety: same write-guard triad as ticket-validate.mjs (unset target -> 'env_fail' verdict;
 * explicit production default -> FAIL; otherwise pinned to 17233/suyou-test).  // naming-compat
 */

import { spawn, spawnSync } from 'node:child_process'
import { connect } from 'node:net'
import { existsSync } from 'node:fs'
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const POC = join(REPO, 'server', 'engine')
const COMPOSE = join(REPO, 'server', 'docker-compose.test.yml')
export const PROD_ADDR = '127.0.0.1:7233'
export const TEST_ADDR = '127.0.0.1:17233'
export const TEST_NS = 'suyou-test'  // naming-compat
const EPIC_CODE = 'integ-e2e'

/* ------------------------------------------------------------------ assertions */

export function makeTally() {
  const t = { pass: 0, fail: 0, envFail: 0, failures: [] }
  t.ok = (cond, label) => {
    if (cond) { t.pass++; console.log(`  ok ${label}`) } else {
      t.fail++; t.failures.push(label); console.error(`  FAIL ${label}`)
    }
  }
  t.envFailNote = (label) => { t.envFail++; console.log(`  ENV_FAIL ${label}`) }
  t.section = (s) => console.log(`\n== ${s}`)
  return t
}

/* ------------------------------------------------------------------ processes */

/** spawnSync a command, returning {status, stdout, stderr} with strings. */
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: opts.timeoutMs ?? 60_000, ...opts })
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' }
}

/** spawn a long-lived child with an owner that can always reap it (TERM -> KILL). */
export function own(child) {
  const o = { child, done: false, reaped: false }
  child.once('exit', () => { o.done = true })
  o.kill = async (sig = 'SIGTERM') => {
    if (o.done) return
    try { child.kill(sig) } catch { /* already dead */ }
    for (let i = 0; i < 50 && !o.done; i++) await new Promise(r => setTimeout(r, 100))
    if (!o.done) { try { child.kill('SIGKILL') } catch { /* already dead */ } }
    await new Promise(r => {
      if (o.done) return r()
      child.once('exit', r)
      setTimeout(r, 5000).unref?.()
    })
    o.reaped = !child.pid || (() => { try { process.kill(child.pid, 0); return false } catch { return true } })()
  }
  return o
}

/* ------------------------------------------------------------------ environment */

export async function portOpen(host, port, ms = 1500) {
  return new Promise((resolve) => {
    const s = connect({ host, port })
    const fin = (v) => { s.destroy(); resolve(v) }
    s.setTimeout(ms, () => fin(false))
    s.once('connect', () => fin(true))
    s.once('error', () => fin(false))
  })
}

/**
 * Locate a python that can import temporalio (the SDK the engine needs).
 * Preference: the repo-local venv, the main checkout's venv (worktrees share the
 * common .git; prepare_workspace links the same source into lanes), then plain
 * python3. Returns null when absent.
 */
export function findSdkPython(t) {
  const mainVenv = run('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
  const mainCheckout = mainVenv.status === 0 ? dirname(mainVenv.stdout.trim()) : ''
  const candidates = [
    join(POC, '.venv', 'bin', 'python'),
    ...(mainCheckout ? [join(mainCheckout, 'server', 'engine', '.venv', 'bin', 'python')] : []),
    'python3',
  ]
  for (const py of candidates) {
    const r = run(py, ['-c', 'import temporalio'], { timeoutMs: 30_000 })
    if (r.status === 0) return py
  }
  t?.envFailNote?.('temporalio SDK not importable (no server/engine/.venv here or in the main checkout, system python3 lacks it): env halves cannot drive real client.py/worker')
  return null
}

/**
 * Ensure the Docker test Temporal (17233) is reachable: probe first, then an
 * idempotent `docker compose up -d`, then re-probe. Returns true/false.
 */
export async function ensureTestTemporal(t) {
  if (await portOpen('127.0.0.1', 17233)) return true
  const docker = run('docker', ['--version'], { timeoutMs: 10_000 })
  if (docker.status !== 0) {
    t?.envFailNote?.(`docker CLI unavailable (test Temporal 17233 down and cannot be pulled up): ${docker.stderr.trim().slice(0, 120) || 'command not found'}`)
    return false
  }
  console.log('  test Temporal 17233 down -> docker compose up -d (idempotent) ...')
  run('docker', ['compose', '-f', COMPOSE, 'up', '-d'], { timeoutMs: 300_000 })
  for (let i = 0; i < 60; i++) {
    if (await portOpen('127.0.0.1', 17233)) return true
    await new Promise(r => setTimeout(r, 2000))
  }
  t?.envFailNote?.('docker compose up ran but test Temporal 17233 never opened: test env unavailable')
  return false
}

/**
 * Write-guard, tri-state (same contract as ticket-validate.mjs):
 * returns 'run' | 'env_fail' | 'fail'（writeGuard 三值裁决词，是本助手对场景声明的
 * API，被 sc_ticket_lifecycle P1 正向断言；t260904-12 三态契约对齐：unset target
 * 的裁决词从旧跳过词改用环境红词 env_fail，三值形状与正向断言面不变）.
 * Never run with an unclear target.
 */
export function writeGuard() {
  const target = process.env.SANDBAR_TARGET_HOST
  if (target === PROD_ADDR) {
    console.error(`  FAIL write-guard: SANDBAR_TARGET_HOST explicitly points at production default ${PROD_ADDR} -- ticket-creating tests refuse to run (red line: production 7233 is read-only)`)
    return 'fail'
  }
  if (target === undefined || target === '') return 'env_fail'
  if (target !== TEST_ADDR) {
    console.error(`  FAIL write-guard: SANDBAR_TARGET_HOST=${target} is neither the pinned test env ${TEST_ADDR} nor production -- refusing an unclear write target`)
    return 'fail'
  }
  return 'run'
}

/** Shared env for every client.py/worker invocation (pinned to the test env). */
export function targetEnv(extra = {}) {
  return {
    ...process.env,
    SANDBAR_TARGET_HOST: TEST_ADDR,
    SANDBAR_NAMESPACE: TEST_NS,
    ...extra,
  }
}

/* ------------------------------------------------------------------ fixture repo */

/**
 * Build the disposable fixture repo the stub worker will call home:
 * clone main (depth 1) from the local main checkout, symlink the gitignored
 * dependency dirs (node_modules / engine/.venv) so lane-internal
 * verify_lane can go green, and drop the epic file suggest_next needs.
 * Returns { fixture, dispose } or null (with ENV_FAIL notes) when impossible.
 */
export async function buildFixture(t) {
  const tmp = await mkdtemp(join(tmpdir(), 'integ-e2e-fixture-'))
  const common = run('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
  const mainCheckout = common.status === 0 ? dirname(common.stdout.trim()) : ''
  if (!mainCheckout || !existsSync(mainCheckout)) {
    t?.envFailNote?.(`cannot locate the local main checkout (${common.stderr.trim().slice(0, 120)}): fixture clone source unavailable`)
    await rm(tmp, { recursive: true, force: true }).catch(() => {})
    return null
  }
  const fixture = join(tmp, 'fixture')
  // fixture 跟随被测代码（当前检出 HEAD），不钉 main——引擎契约演进期钉 main 会造
  // 新旧 split-brain（t260907-04 实证：lane client 按新队列名起 workflow × fixture
  // worker 是旧引擎认旧 env = workflow 搁浅）。合并后 lane==main，行为不变。
  const clone = run('git', ['clone', '--depth', '1', REPO, fixture], { timeoutMs: 300_000 })
  if (clone.status !== 0) {
    t?.envFailNote?.(`git clone main failed: ${(clone.stderr || clone.stdout).trim().slice(0, 200)}`)
    await rm(tmp, { recursive: true, force: true }).catch(() => {})
    return null
  }
  run('git', ['-C', fixture, 'config', 'user.email', 'e2e@suyou.test'])
  run('git', ['-C', fixture, 'config', 'user.name', 'integ-e2e'])
  // 项目注册表夹具化（t260907-04 收尾）：机器级 ~/.sandbar/projects 的 key 'suyou'
  // 是已退役 suyou 仓的自动迁移残留（dirs 指向不存在的 ~/Documents/suyou），lane
  // 派生在死项目根上必炸（假象=prepare_workspace 报 git 身份缺失）。场景把注册表
  // 钉进 fixture（SANDBAR_PROJECTS_DIR=fixture/.e2e-projects）：key 不变（引擎须
  // 照常服务存量 key），dirs 指向 fixture 自身，整链密闭不触机器态。
  const projectsDir = join(fixture, '.e2e-projects', 'suyou')
  await mkdir(projectsDir, { recursive: true })
  // .migrated 标记：fixture 表与迁移源（fixture 内克隆来的 projects.yaml 种子）key
  // 相交但内容不同，会被一致性检查判「混合现场」fail-closed——fixture 表是自洽
  // 人工注册表，补标记走「已迁移」跳过判据。
  await writeFile(join(fixture, '.e2e-projects', '.migrated'), 'fixture-local hermetic registry (t260907-04)\n')
  await writeFile(join(projectsDir, 'project.yaml'),
    `# fixture-local registry (t260907-04): hermetic project entry, dirs -> fixture itself\n`
    + 'schema: v1\n'
    + 'project:\n'
    + '  - key: suyou\n'
    + '    name: integ-e2e-fixture\n'
    + '    dirs:\n'
    + `      - ${fixture}\n`)
  // Dependency symlinks: prepare_workspace links gitignored dirs from the worker's
  // REPO_ROOT (the fixture) into the lane; give the fixture something to link.
  for (const [link, target] of [
    [join(fixture, 'app', 'node_modules'), join(mainCheckout, 'app', 'node_modules')],
    [join(fixture, 'server', 'engine', '.venv'), join(mainCheckout, 'server', 'engine', '.venv')],
  ]) {
    if (existsSync(target)) {
      await mkdir(dirname(link), { recursive: true })
      await symlink(target, link).catch(() => {})
    }
  }
  // Epic archive for the suggest_next contract (worker-side EPICS_DIR = fixture).
  await mkdir(join(fixture, 'notes', 'epics'), { recursive: true })
  await writeFile(join(fixture, 'notes', 'epics', `${EPIC_CODE}.md`),
    '# 立项单：integ-e2e\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `integ-e2e` |\n| 状态 | 已立项（执行中） |\n', 'utf8')
  const dispose = async () => { await rm(tmp, { recursive: true, force: true }).catch(() => {}) }
  return { fixture, mainCheckout, tmp, dispose }
}

/* ------------------------------------------------------------------ client.py bridge */

function client(sdkPython, op, args, extraEnv = {}) {
  const env = targetEnv()
  if (extraEnv.epicsDir) env.SANDBAR_EPICS_DIR = extraEnv.epicsDir
  if (extraEnv.projectsDir) env.SANDBAR_PROJECTS_DIR = extraEnv.projectsDir
  const r = run(sdkPython, [join(POC, 'client.py'), op, JSON.stringify(args)],
    { env, timeoutMs: extraEnv.timeoutMs ?? 120_000 })
  let body = null
  try { body = JSON.parse(r.stdout) } catch { /* surfaced below */ }
  return { ...r, body }
}

export function makeApi(sdkPython, fixture) {
  const epicsDir = join(fixture, 'notes', 'epics')
  const env = { epicsDir, projectsDir: join(fixture, '.e2e-projects') }
  return {
    async start(ticketId, writeSet) {
      return client(sdkPython, 'ticket-start', {
        ticket_id: ticketId, template_id: 'dev-lane', project: 'suyou',
        title: `[e2e] 工单全链 ${ticketId}`, epic: EPIC_CODE,
        user_request: 'integration baseline: stub-brain full-chain ticket lifecycle',
        write_set: writeSet,
      }, env)
    },
    query: (tid) => client(sdkPython, 'ticket-query', { ticket_id: tid }, env),
    sign: (tid, who, decision, note, gate = 'merge') =>
      client(sdkPython, 'ticket', { op: 'sign', ticket_id: tid, input: { who, gate, decision, note } }, env),
    rework: (tid, toStage, note, who = 'e2e') =>
      client(sdkPython, 'ticket', { op: 'rework', ticket_id: tid, to_stage: toStage, note, who }, env),
    cancel: (tid) => client(sdkPython, 'cancel', { workflow_id: tid }, env),
  }
}

/* ------------------------------------------------------------------ worker */

/**
 * Start the per-ticket stub worker from the fixture's own engine (so its
 * REPO_ROOT is the fixture). WATCH mode self-exits when the workflow reaches a
 * non-RUNNING state; the owner handles blocked-steady-state and failure paths.
 */
export function startStubWorker(fixture, sdkPython, ticketId) {
  const child = spawn(sdkPython, [join(fixture, 'server', 'engine', 'worker.py')], {
    env: targetEnv({
      SANDBAR_TASK_QUEUES: `sandbar-ticket-${ticketId},suyou-ticket-${ticketId}`,  // naming-compat（新旧双前缀 CSV=ticket_worker.spawn 同款契约，t260907-04）
      SANDBAR_PROJECTS_DIR: join(fixture, '.e2e-projects'),  // 项目注册表夹具化（t260907-04：机器种子 key suyou 指向已退役仓）
      SANDBAR_WATCH_WORKFLOW: ticketId,
      // watch 快档（t260905-02 旋钮）：场景收口 cancel 后 worker 自退从慢档 30s×轮
      // 缩到 ~4s——cleanupTicket 的 90s 等退窗口此前恒被慢档吃满（260909 计时实锤）。
      SANDBAR_WATCH_INTERVAL_SEC: '4',
      SANDBAR_AGENT_STUB: '1',
      SANDBAR_SUGGEST_STUB: 'ok',
      SANDBAR_UI_CAPTURE_STUB: '1',
    }),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stderr.on('data', () => {}) // drained; keep the pipe from backing up
  child.stdout.on('data', () => {})
  return own(child)
}

/* ------------------------------------------------------------------ driving helpers */

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

/** Poll ticket-query until pred(snapshot) holds. Returns last snapshot or null. */
export async function waitFor(api, tid, pred, label, deadlineMs, t) {
  const end = Date.now() + deadlineMs
  let snap = null
  while (Date.now() < end) {
    const r = api.query(tid)
    snap = r.body?.ok ? r.body.result.snapshot : null
    if (snap && pred(snap)) return snap
    if (!snap && r.body && r.body.ok === false && /不存在|not found/i.test(r.body.error || '')) {
      t?.ok?.(false, `${label}: workflow disappeared (${r.body.error})`)
      return null
    }
    await sleep(2000)
  }
  t?.ok?.(false, `${label}: timed out after ${Math.round(deadlineMs / 1000)}s (last stage=${snap?.stage}/${snap?.stage_state})`)
  return null
}

/** Absolute lane worktree path inside the fixture, from a snapshot. */
export function lanePath(fixture, snap) {
  const p = snap?.meta?.workspace?.path || snap?.meta?.worktree || ''
  if (!p) return ''
  return p.startsWith('/') ? p : join(fixture, p)
}

/**
 * Pre-seed the NEXT arbitrate result file (max existing gen + 1) with a
 * verdict=pass summary. Called while the ticket is busy in
 * run_integration_tests: the idempotent cache then returns it deterministically.
 */
export async function seedArbitratePass(lane) {
  const dir = join(lane, '.suyou')  // naming-compat
  let maxGen = -1
  if (existsSync(dir)) {
    for (const f of await readdir(dir)) {
      const m = /^stage_arbitrate_gen(\d+)\.json$/.exec(f)
      if (m) maxGen = Math.max(maxGen, Number(m[1]))
    }
  }
  const gen = maxGen + 1
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, `stage_arbitrate_gen${gen}.json`), JSON.stringify({
    status: 'ok',
    summary: '集成测试三态判定：verdict=pass（全部机械测试通过；E2E 预置结果文件，走引擎幂等缓存路径）',
    report: '[e2e seeded] verdict=pass',
    deliverables: [], files_changed: [],
    evidence: 'seeded by integration/baselines ticket-lifecycle (stub-brain determinism lever)',
    prompt: '(seeded; real prompt patched by _patch_result_prompt on cache hit)',
  }, null, 1) + '\n', 'utf8')
  return gen
}

/** Drop a probe file into the lane (integration/ is write-set exempt). */
export async function writeProbe(lane, name) {
  const p = join(lane, 'integration', name)
  await mkdir(dirname(p), { recursive: true })
  await writeFile(p, `probe written by ticket-lifecycle e2e at ${new Date().toISOString()}\n`, 'utf8')
  return p
}

/* ------------------------------------------------------------------ scenes */

const SCENE_DEADLINE_MS = 10 * 60 * 1000 // ticket contract: <=10 min per scene

async function driveToMergeGate(t, api, sdkPython, fixture, tid, seed = true) {
  // 1) workspace ready -> write the probe (must be dirty before the join settle)
  const ready = await waitFor(api, tid, (s) => !!s?.meta?.workspace_prep?.ok,
    'workspace ready', 120_000, t)
  if (!ready) return null
  const lane = lanePath(fixture, ready)
  if (!lane) { t.ok(false, 'snapshot.meta.workspace.path missing'); return null }
  const probeName = `e2e-probe-${tid}.txt`
  await writeProbe(lane, probeName)
  // 2) while run_integration_tests is mechanically busy, seed arbitrate verdict=pass
  if (seed) {
    const s = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'run_integration_tests reached', SCENE_DEADLINE_MS, t)
    if (!s) return null
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 0, `arbitrate verdict=pass pre-seeded (gen${gen})`)
  }
  // 3) wait for the human gate
  const snap = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
    'merge human gate', SCENE_DEADLINE_MS, t)
  return snap ? { snap, lane, probeName } : null
}

/** Scene A: happy path full chain -> approve -> closed + lane cleanup + suggest_next. */
export async function sceneA(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-a-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid,[`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || r.stderr).slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    lane = gate.lane
    const s = gate.snap
    const expected = ['workspace', 'create_plan', 'review_plan', 'implement',
      'design_integration_tests', 'run_integration_tests', 'arbitrate',
      'acceptance_walkthrough', 'merge_check', 'merge']
    const tl = (s.timeline || []).map(e => e.stage)
    const idx = expected.map(st => tl.indexOf(st))
    const seenAll = idx.every(i => i >= 0)
    const inOrder = seenAll && idx.every((v, k) => k === 0 || v > idx[k - 1])
    t.ok(seenAll && inOrder, `timeline covers the full stage chain in STAGES order (got: ${tl.join('>')})`)
    for (const st of ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
      'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check']) {
      t.ok(!!s.results?.[st], `checks ledger has ${st} entry`)
    }
    const mc = (s.gate_runs || []).filter(g => g.stage === 'merge_check').pop()
    t.ok(mc?.green === true, `merge_check four checks green (detail: ${JSON.stringify(mc?.checks?.map(c => [c.item, c.green])) || 'none'})`)
    t.ok(s.signatures?.merge === undefined, 'merge gate is awaiting signature (not yet signed)')
    // write-set exemption evidence: probe committed although integration/ is exempt
    const log = run('git', ['-C', lane, 'log', '--name-only', '--pretty=format:', '-5'])
    t.ok(log.stdout.includes(gate.probeName), 'integration/ probe file landed in a lane commit (write-set exemption)')
    // approve -> real merge + lane cleanup + suggest_next + closed
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 A 放行').body?.ok === true, 'sign approve delivered')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    if (!fin) return
    t.ok(fin.status === 'closed', `terminal status is closed (not legacy settled): ${fin.status}`)
    t.ok(!existsSync(lane), 'lane worktree removed after merge (fixture cleanup)')
    const br = run('git', ['-C', fixture, 'branch', '--list', fin.meta?.branch || 'lane/*'])
    t.ok(!br.stdout.trim(), 'lane branch deleted after merge')
    t.ok(existsSync(join(fixture, '.suyou', 'epic-next', EPIC_CODE, 'pre.json')),  // naming-compat
      'suggest_next pre-ran: fixture .suyou/epic-next/<code>/pre.json exists')  // naming-compat
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene B: merge-gate reject -> back to implement with the note injected -> approve -> closed. */
export async function sceneB(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-b-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const note = 'E2E reject 意见：探针自测不足，请补充'
    const r = await api.start(tid,['integration/README.md'])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    t.ok(api.sign(tid, 'e2e-human', 'reject', note).body?.ok === true, 'sign reject (with note) delivered')
    const atImpl = await waitFor(api, tid, (x) => x?.stage === 'implement',
      'reject routed back to implement', SCENE_DEADLINE_MS, t)
    if (!atImpl) return
    t.ok(String(atImpl.meta?.log?.map(l => l.note).join('｜')).includes('人在 merge 打回'),
      'reject logged as human merge rework')
    // the redo re-enters arbitrate with gen1: seed it again during the manifest
    // re-run, or the stub brain's missing verdict= hits the format-round limit
    const busy2 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'manifest re-running after reject', SCENE_DEADLINE_MS, t)
    if (!busy2) return
    const gen = await seedArbitratePass(lanePath(fixture, busy2))
    t.ok(gen >= 1, `arbitrate pass re-seeded for the redo (gen${gen})`)
    const back = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'back at merge gate after redo', SCENE_DEADLINE_MS, t)
    if (!back) return
    // prev_ctx assertion: read the lane result file directly (snapshot results carry no prompt)
    const impl1 = join(lanePath(fixture, back), '.suyou', 'stage_implement_gen1.json')  // naming-compat
    let prompt = ''
    try { prompt = JSON.parse(await readFile(impl1, 'utf8')).prompt || '' } catch { /* below */ }
    t.ok(prompt.includes(`人在 merge 打回：${note}`), 'redo prompt injects the reject note (prev_ctx via lane result file)')
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 B 复核通过').body?.ok === true, 'second visit: sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'reject->redo->approve chain ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene C: manual rework (real route + context inheritance + gen bump) + malformed signals. */
export async function sceneC(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-c-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const r = await api.start(tid,['integration/manifest.json'])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // malformed #1: sign while the ticket is NOT awaiting-human (still running create_plan)
    const running = await waitFor(api, tid, (x) => x?.stage === 'create_plan', 'create_plan running', 120_000, t)
    if (!running) return
    const refusedBefore = (running.refused || []).length
    api.sign(tid, 'e2e-human', 'approve', ' premature sign (should be refused) ')
    const after = await waitFor(api, tid, (x) => (x?.refused || []).length > refusedBefore,
      'premature sign lands in refused', 60_000, t)
    t.ok(!!after && (after.refused || []).length > refusedBefore,
      'malformed sign (non-awaiting state) -> refused entry, stage untouched')
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    // malformed #2/#3: rework to a nonexistent stage and to an inline stage
    const refusedAtGate = (gate.snap.refused || []).length
    api.rework(tid, 'no_such_stage_xyz', 'E2E malformed rework: nonexistent target')
    const m2 = await waitFor(api, tid, (x) => (x?.refused || []).length > refusedAtGate,
      'rework(nosuch) refused', 60_000, t)
    t.ok(!!m2 && m2.stage === 'merge' && m2.stage_state === 'awaiting-human',
      'malformed rework (nonexistent stage) -> refused, ticket stays at the merge gate')
    api.rework(tid, 'suggest_next', 'E2E malformed rework: inline stage')
    const m3 = await waitFor(api, tid, (x) => (x?.refused || []).length > (m2?.refused || []).length,
      'rework(suggest_next) refused', 60_000, t)
    t.ok(!!m3 && m3.stage === 'merge' && m3.stage_state === 'awaiting-human',
      'malformed rework (inline suggest_next) -> refused, ticket stays at the merge gate')
    // legal rework: back to acceptance_walkthrough (real STAGES id)
    const note = 'E2E rework 意见：走查报告需补充边界场景'
    t.ok(api.rework(tid, 'acceptance_walkthrough', note).body?.ok === true, 'rework -> acceptance_walkthrough delivered')
    const atAcc = await waitFor(api, tid, (x) => x?.stage === 'acceptance_walkthrough',
      'routed back to acceptance_walkthrough', SCENE_DEADLINE_MS, t)
    if (!atAcc) return
    const back = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'back at merge gate after rework loop', SCENE_DEADLINE_MS, t)
    if (!back) return
    const acc1 = join(lanePath(fixture, back), '.suyou', 'stage_acceptance_walkthrough_gen1.json')  // naming-compat
    let prompt = ''
    try { prompt = JSON.parse(await readFile(acc1, 'utf8')).prompt || '' } catch { /* below */ }
    t.ok(prompt.includes(note), 'rework prompt inherits the note (context inheritance, lane result file)')
    t.ok(String(back.meta?.last_rework_note || '') === note, 'meta.last_rework_note recorded (round accounting)')
    const gens = (back.timeline || []).filter(e => e.stage === 'acceptance_walkthrough').length
    t.ok(gens >= 2, `acceptance_walkthrough re-entered (gen bump, timeline entries=${gens})`)
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 C 收口').body?.ok === true, 'sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'rework loop ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene D: no verdict seed -> real round-limit (arbitrate format rounds) -> blocked -> revive. */
export async function sceneD(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-d-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid,[`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // Deviation note (ticket body D asked for "round limit via repeated merge rejects";
    // the engine has no reject round counter -- this scene exercises the real limit:
    // the stub brain's arbitrate summary lacks verdict=, 3 format-correction rounds -> blocked)
    // The probe must dirty the lane BEFORE the parallel-join settle: that junction
    // commit is what satisfies run_integration_tests' 0-commit precheck ("实现未落盘").
    // Waiting for the mechanical step itself is too late -- the precheck fires first
    // and would block with the wrong reason. So: probe at workspace-ready, then wait.
    const ready = await waitFor(api, tid, (x) => !!x?.meta?.workspace_prep?.ok,
      'workspace ready', 120_000, t)
    if (!ready) return
    lane = lanePath(fixture, ready)
    await writeProbe(lane, probeName)
    const blocked = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'arbitrate round-limit -> blocked', SCENE_DEADLINE_MS, t)
    if (!blocked) return
    const logs = (blocked.meta?.log || []).map(l => l.note).join('｜')
    t.ok(blocked.stage === 'arbitrate', 'blocked at arbitrate (stage preserved)')
    t.ok(logs.includes('缺 verdict= 标记'), 'blocked note names the missing verdict= marker')
    t.ok((blocked.timeline || []).filter(e => e.stage === 'arbitrate').length >= 3,
      'three arbitrate format rounds in the timeline (round limit reached)')
    // revive: rework -> implement; seed the next arbitrate gen while the manifest re-runs
    t.ok(api.rework(tid, 'implement', 'E2E：补预置后重跑').body?.ok === true, 'rework -> implement (revive)')
    const busy = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'manifest re-running after revive', SCENE_DEADLINE_MS, t)
    if (!busy) return
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 1, `arbitrate pass seeded at polled gen${gen} (not statically guessed)`)
    const gate = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'revived ticket reaches merge gate', SCENE_DEADLINE_MS, t)
    if (!gate) return
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 D 收口').body?.ok === true, 'sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'blocked -> rework -> approve chain ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene E: write-set lifecycle assertions on a dedicated ticket (refresh + exemption). */
export async function sceneE(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-e-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const initialWs = [`integration/${probeName}`, 'integration/README.md']
    const r = await api.start(tid,initialWs)
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const ready = await waitFor(api, tid, (x) => !!x?.meta?.workspace_prep?.ok, 'workspace ready', 120_000, t)
    if (!ready) return
    const lane = lanePath(fixture, ready)
    await writeProbe(lane, probeName)
    // initial write_set recorded verbatim
    t.ok(JSON.stringify([...(ready.meta?.write_set || [])].sort()) === JSON.stringify([...initialWs].sort()),
      `initial meta.write_set equals ticket-start input (${JSON.stringify(ready.meta?.write_set)})`)
    // after review_plan finalizes the plan the write set is refreshed (union; stub
    // files_changed=[] keeps the set, and the log line makes it explicit)
    const refreshed = await waitFor(api, tid,
      (x) => String((x?.meta?.log || []).map(l => l.note).join('｜')).includes('写集已随方案定稿刷新'),
      'write-set refreshed on plan finalization', SCENE_DEADLINE_MS, t)
    if (!refreshed) return
    t.ok((refreshed.meta?.write_set || []).length >= initialWs.length,
      'meta.write_set after refresh still covers the initial set (union semantics)')
    // authorized extension, pure-function half (deterministic, no race): refresh_write_set
    // unions plan files into the set and books "授权扩展" for the additions
    const py = run(sdkPython, ['-c', `
import sys, json
sys.path.insert(0, ${JSON.stringify(POC)})
from shared import refresh_write_set
merged, added, dropped = refresh_write_set(["a.txt"], ["integration/new-probe.txt", "a.txt"])
print(json.dumps({"merged": merged, "added": added, "dropped": dropped}))`], { timeoutMs: 30_000 })
    let ext = null
    try { ext = JSON.parse(py.stdout.trim()) } catch { /* surfaced by the assert below */ }
    t.ok(ext?.merged?.includes('integration/new-probe.txt') && (ext?.added || []).includes('integration/new-probe.txt'),
      'refresh_write_set unions plan files (authorized extension) and integration/ entries survive')
    // exemption half: the integration/ probe (not even listed as writable code) is
    // committed by settle_lane and keeps verify_lane's write-set whitelist green
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    const log = run('git', ['-C', gate.lane, 'log', '--name-only', '--pretty=format:', '-5'])
    t.ok(log.stdout.includes(probeName), 'integration/ probe committed (exemption holds in the real settle)')
    const mc = (gate.snap.gate_runs || []).filter(g => g.stage === 'merge_check').pop()
    const wsCheck = (mc?.checks || []).find(c => String(c.item).includes('写集白名单'))
    t.ok(mc?.green === true && (wsCheck === undefined || wsCheck.green === true),
      'merge_check green with the probe in the commit (whitelist + exemption)')
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 E 收口').body?.ok === true, 'sign approve')
    await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/* ------------------------------------------------------------------ cleanup */

/**
 * Best-effort ticket cancel + worker reap + fixture dispose. Unlike the borrowed
 * integration-baseline pattern, a lingering integ-e2e ticket is OUR subject, so
 * cancel failures surface as scene failures (no silent namespace pollution).
 */
export async function cleanupTicket(t, api, worker, tid) {
  try {
    const q = api.query(tid)
    const status = q.body?.result?.status
    if (status === 'RUNNING') {
      const c = api.cancel(tid)
      // client.py cancel keys on workflow_id (= ticket id for dev-lane tickets)
      if (c.body?.ok !== true) t.ok(false, `cancel ${tid} failed: ${(c.body?.error || c.stderr).slice(0, 120)}`)
    }
  } catch { /* query failed: workflow likely already gone */ }
  if (worker) {
    const deadline = Date.now() + 90_000 // WATCH self-exit for closed/cancelled
    while (!worker.done && Date.now() < deadline) await sleep(1000)
    if (!worker.done) await worker.kill() // blocked steady-state or hung: owner reaps
    t.ok(worker.done || worker.reaped, `worker for ${tid} fully reaped (WATCH exit or owner kill)`)
  }
}

export const SCENE_TIMEOUT_BUDGET_MS = SCENE_DEADLINE_MS
