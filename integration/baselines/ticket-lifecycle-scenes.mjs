/**
 * ticket-lifecycle E2E 基线的场景库（group 5）。
 *
 * 什么是真的：Docker 测试 Temporal（17233 / namespace suyou-test）、真 per-ticket
 * worker（worker.py 跑专属队列，WATCH 自退）、真引擎链（prepare_workspace →
 * create_plan ↔ review_plan → implement || design_integration_tests →
 * run_integration_tests → arbitrate → acceptance_walkthrough → merge_check →
 * merge [人审闸] → suggest_next inline → status=closed）、真 settle/merge/泳道清理，
 * 人审信号走真 client.py。
 *
 * 什么是桩：只有 agent 大脑（SANDBAR_AGENT_STUB=1 时段自完成、
 * SANDBAR_SUGGEST_STUB=ok，零模型调用）。
 *
 * 隔离（merge 落在 worker 侧 REPO_ROOT 当前分支、忽略 base_ref，见 agent_activities.py
 * merge()）：每个场景对一棵一次性「夹具仓」跑——本地 main 的 --depth 1 clone。
 * worker 从夹具仓自己的 engine 起，REPO_ROOT=夹具仓：泳道、settle、merge、泳道
 * 清理全发生在夹具仓里，真仓永不被碰。
 *
 * 确定性杠杆：agent 段在结果文件已存在时直接返回缓存（agent_activities.py 幂等
 * 缓存路）。场景在票机械地忙在 run_integration_tests 时预种
 * `.suyou/stage_arbitrate_gen<N>.json`（summary 带 verdict=pass）——stub 大脑自己
 * 永不产出 verdict=，这本身就是场景 D 的轮次上限触发器。
 *
 * 安全：与 ticket-validate.mjs 同款写集三件套（target env 未设→env_fail；
 * 显式生产默认→FAIL；否则钉死 17233/suyou-test）。
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

/** spawnSync 一把命令，返回字符串形态的 {status, stdout, stderr}。 */
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: opts.timeoutMs ?? 60_000, ...opts })
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' }
}

/** spawn 长命子进程，配一个永远能收割它的 owner（TERM 不退就 KILL）。 */
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
 * 找一个能 import temporalio 的 python（引擎 SDK 需要）。
 * 优先序：本树 venv → 主 checkout 的 venv（worktree 共享 .git；
 * prepare_workspace 会把同源链进泳道）→ 裸 python3。都没有返回 null。
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
 * 确保 Docker 测试 Temporal（17233）可达：先探活，再幂等
 * `docker compose up -d`，再探一次。返回 true/false。
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
 * Write-guard 三态（与 ticket-validate.mjs 同款合同）：返回
 * 'run' | 'env_fail' | 'fail'。target env 未设=env_fail（票 t260904-12 三态契约：
 * 缺环境用环境红词，不用跳过词）；显式指生产=fail；其余不明目标=fail。
 * 目标不清楚就绝不开跑。
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

/** 每次 client.py/worker 调用的共享 env（钉死测试环境）。 */
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
 * 造一次性夹具仓（stub worker 的家）：从本地 checkout clone（depth 1），软链
 * gitignored 依赖目录（node_modules / engine/.venv，泳道内 verify_lane 要靠它们
 * 跑绿），放下 suggest_next 需要的立项单文件。返回 { fixture, dispose }；
 * 不可能时返回 null（带 ENV_FAIL 注记）。
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
  // fixture 跟随当前检出 HEAD，不钉 main：引擎契约演进期钉 main 会造新旧
  // split-brain（票 t260907-04 实证：lane client 按新队列名起 workflow，fixture
  // worker 是旧引擎认旧 env=workflow 搁浅）。合并后 lane==main，行为不变。
  const clone = run('git', ['clone', '--depth', '1', REPO, fixture], { timeoutMs: 300_000 })
  if (clone.status !== 0) {
    t?.envFailNote?.(`git clone main failed: ${(clone.stderr || clone.stdout).trim().slice(0, 200)}`)
    await rm(tmp, { recursive: true, force: true }).catch(() => {})
    return null
  }
  run('git', ['-C', fixture, 'config', 'user.email', 'e2e@suyou.test'])
  run('git', ['-C', fixture, 'config', 'user.name', 'integ-e2e'])
  // 项目注册表夹具化（票 t260907-04）：机器级注册表的 suyou key 指向已退役仓
  // （自动迁移残留，dirs 是死路径），lane 派生在死项目根上必炸（假象=prepare_workspace
  // 报 git 身份缺失）。场景把注册表钉进 fixture：key 不变（引擎须照常服务存量 key），
  // dirs 指向 fixture 自身，整链密闭不触机器态。
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
  // 依赖软链：prepare_workspace 会把 worker REPO_ROOT（=fixture）里 gitignored 的
  // 目录软链进泳道；先给 fixture 备好链接目标。
  for (const [link, target] of [
    [join(fixture, 'app', 'node_modules'), join(mainCheckout, 'app', 'node_modules')],
    [join(fixture, 'server', 'engine', '.venv'), join(mainCheckout, 'server', 'engine', '.venv')],
  ]) {
    if (existsSync(target)) {
      await mkdir(dirname(link), { recursive: true })
      await symlink(target, link).catch(() => {})
    }
  }
  // suggest_next 需要的立项单档案（worker 侧 EPICS_DIR=fixture）。
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
 * 从 fixture 仓自己的 engine 起 per-ticket stub worker（REPO_ROOT=fixture）。
 * WATCH 模式在 workflow 离开 RUNNING 后自退；blocked 稳态与失败路径由 owner 兜底。
 */
export function startStubWorker(fixture, sdkPython, ticketId) {
  const child = spawn(sdkPython, [join(fixture, 'server', 'engine', 'worker.py')], {
    env: targetEnv({
      SANDBAR_TASK_QUEUES: `sandbar-ticket-${ticketId},suyou-ticket-${ticketId}`,  // naming-compat（新旧双前缀 CSV=ticket_worker.spawn 同款契约，t260907-04）
      SANDBAR_PROJECTS_DIR: join(fixture, '.e2e-projects'),  // 注册表夹具化（票 t260907-04：机器种子 key 指向已退役仓）
      SANDBAR_WATCH_WORKFLOW: ticketId,
      // watch 快档（票 t260905-02 旋钮）：场景收口 cancel 后 worker 自退从慢档
      // 30s×轮缩到 ~4s——cleanupTicket 的 90s 等退窗口此前恒被慢档吃满（260909 计时实锤）。
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

/** 轮询 ticket-query 直到 pred(snapshot) 成立。返回最后的 snapshot 或 null。 */
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

/** 从 snapshot 推 fixture 内泳道 worktree 的绝对路径。 */
export function lanePath(fixture, snap) {
  const p = snap?.meta?.workspace?.path || snap?.meta?.worktree || ''
  if (!p) return ''
  return p.startsWith('/') ? p : join(fixture, p)
}

/**
 * 预种下一代 arbitrate 结果文件（最大已有 gen + 1），summary 带 verdict=pass。
 * 调用时机=票忙在 run_integration_tests 时：幂等缓存随后确定性地返回它。
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

/** 往泳道丢一个探针文件（integration/ 在写集豁免名单里）。 */
export async function writeProbe(lane, name) {
  const p = join(lane, 'integration', name)
  await mkdir(dirname(p), { recursive: true })
  await writeFile(p, `probe written by ticket-lifecycle e2e at ${new Date().toISOString()}\n`, 'utf8')
  return p
}

/* ------------------------------------------------------------------ scenes */

const SCENE_DEADLINE_MS = 10 * 60 * 1000 // ticket contract: <=10 min per scene

async function driveToMergeGate(t, api, sdkPython, fixture, tid, seed = true) {
  // 1) workspace 就绪→写探针（必须在 join settle 之前弄脏泳道）
  const ready = await waitFor(api, tid, (s) => !!s?.meta?.workspace_prep?.ok,
    'workspace ready', 120_000, t)
  if (!ready) return null
  const lane = lanePath(fixture, ready)
  if (!lane) { t.ok(false, 'snapshot.meta.workspace.path missing'); return null }
  const probeName = `e2e-probe-${tid}.txt`
  await writeProbe(lane, probeName)
  // 2) run_integration_tests 机械忙段，预种 arbitrate verdict=pass
  if (seed) {
    const s = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'run_integration_tests reached', SCENE_DEADLINE_MS, t)
    if (!s) return null
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 0, `arbitrate verdict=pass pre-seeded (gen${gen})`)
  }
  // 3) 等人审闸
  const snap = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
    'merge human gate', SCENE_DEADLINE_MS, t)
  return snap ? { snap, lane, probeName } : null
}

/** 场景 A：全链 happy path → 批准 → closed + 泳道清理 + suggest_next。 */
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
    // 写集豁免证据：integration/ 虽豁免，探针仍被提交
    const log = run('git', ['-C', lane, 'log', '--name-only', '--pretty=format:', '-5'])
    t.ok(log.stdout.includes(gate.probeName), 'integration/ probe file landed in a lane commit (write-set exemption)')
    // 批准→真 merge + 泳道清理 + suggest_next + closed
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

/** 场景 B：merge 人审拒绝→带注记回到 implement→再批准→closed。 */
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
    // 重做以 gen1 重进 arbitrate：manifest 重跑时再种一次，否则 stub 大脑缺
    // verdict=会撞格式轮上限
    const busy2 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'manifest re-running after reject', SCENE_DEADLINE_MS, t)
    if (!busy2) return
    const gen = await seedArbitratePass(lanePath(fixture, busy2))
    t.ok(gen >= 1, `arbitrate pass re-seeded for the redo (gen${gen})`)
    const back = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'back at merge gate after redo', SCENE_DEADLINE_MS, t)
    if (!back) return
    // prev_ctx 断言：直接读泳道结果文件（snapshot 结果不带 prompt）
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

/** 场景 C：人工打回（真路由 + 上下文继承 + gen 递增）+ 畸形信号。 */
export async function sceneC(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-c-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const r = await api.start(tid,['integration/manifest.json'])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // 畸形 #1：票未等人审时 sign（还在 create_plan）
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
    // 畸形 #2/#3：rework 到不存在的段、rework 到 inline 段
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
    // 合法 rework：回到 acceptance_walkthrough（真 STAGES id）
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

/** 场景 D：不种 verdict → 真轮次上限（arbitrate 格式轮）→ blocked → 复活。 */
export async function sceneD(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-d-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid,[`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // 偏离注记（票身 D 原写「merge 反复拒绝触轮限」；引擎没有拒绝计数器——
    // 本场景走真上限：stub 大脑 arbitrate summary 缺 verdict=，3 轮格式纠正→blocked）
    // 探针必须在并行 join 的 settle 之前弄脏泳道：正是那个交汇 commit 满足
    // run_integration_tests 的 0-commit 预检（「实现未落盘」）。等机械步本身就来不及——
    // 预检先触发，会以错误的理由 block。所以：workspace 一就绪就写探针，再等。
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
    // 复活：rework→implement；manifest 重跑时种下一代 arbitrate
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

/** 场景 E：专票上的写集生命周期断言（刷新 + 豁免）。 */
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
    // 初始 write_set 原样入账
    t.ok(JSON.stringify([...(ready.meta?.write_set || [])].sort()) === JSON.stringify([...initialWs].sort()),
      `initial meta.write_set equals ticket-start input (${JSON.stringify(ready.meta?.write_set)})`)
    // review_plan 定稿后写集刷新（并集；stub files_changed=[] 不动集合，
    // 日志行使这一点显式）
    const refreshed = await waitFor(api, tid,
      (x) => String((x?.meta?.log || []).map(l => l.note).join('｜')).includes('写集已随方案定稿刷新'),
      'write-set refreshed on plan finalization', SCENE_DEADLINE_MS, t)
    if (!refreshed) return
    t.ok((refreshed.meta?.write_set || []).length >= initialWs.length,
      'meta.write_set after refresh still covers the initial set (union semantics)')
    // 授权扩展纯函数半（确定性、无竞态）：refresh_write_set 把 plan 文件并入
    // 集合并为新增项记「授权扩展」
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
    // 豁免半：integration/ 探针（根本不在可写代码名单里）被 settle_lane 提交，
    // verify_lane 的写集白名单保持绿
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
 * 尽力收口：cancel 票 + 收割 worker + 处理夹具仓。与借来的集成基线模式不同：
 * 残留的 integ-e2e 票是**我们自己的**被测对象，所以 cancel 失败要算场景红
 * （不许静默污染 namespace）。
 */
export async function cleanupTicket(t, api, worker, tid) {
  // 先探终态；探不到（查询超时——blocked 重试风暴期 query 会被饿到超时，260909
  // 实锤）绝不跳过 cancel：旧实现 query 一抛异常就整体跳过，cancel 永远发不出去，
  // worker 只能等 90s deadline 被强杀。
  let closed = false
  try {
    const q = api.query(tid)
    closed = q.body?.result?.status === 'closed'
  } catch { /* 查询失败按未终态处理：cancel 是尽力收口，不制造假红 */ }
  if (!closed) {
    try {
      const c = api.cancel(tid)
      // client.py cancel 按 workflow_id 键（dev-lane 票=票号）；
      // 已终态/已不在册的 benign 报错不算失败。
      const errTxt = String((c && (c.body?.error || c.stderr)) || '')
      const benign = /not[ -]?found|不存在|already completed|已收口|已终态|closed/i.test(errTxt)
      if (c.body?.ok !== true && !benign) {
        t.ok(false, `cancel ${tid} failed: ${errTxt.slice(0, 120)}`)
      }
    } catch (e) {
      t.ok(false, `cancel ${tid} threw: ${String(e).slice(0, 120)}`)
    }
  }
  if (worker) {
    const deadline = Date.now() + 90_000 // WATCH self-exit for closed/cancelled
    while (!worker.done && Date.now() < deadline) await sleep(1000)
    if (!worker.done) await worker.kill() // blocked steady-state or hung: owner reaps
    t.ok(worker.done || worker.reaped, `worker for ${tid} fully reaped (WATCH exit or owner kill)`)
  }
}

export const SCENE_TIMEOUT_BUDGET_MS = SCENE_DEADLINE_MS
