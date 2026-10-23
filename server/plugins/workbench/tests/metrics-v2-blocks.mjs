/**
 * tests/metrics-v2-blocks.mjs —— metrics v2 数据层单测（t261021-06，契约
 * docs/design/metrics-api-contract-v2.md）。
 *
 * 直跑：node server/plugins/workbench/tests/metrics-v2-blocks.mjs（node ≥22.18
 * 原生 type-stripping）。全桩化（SANDBAR_METRICS_STUB + SANDBAR_METRICS_DIR 临时
 * 目录），零真实 ~/.sandbar / admin.py / git 触碰；会话 fixture 用系统 zstd 现场
 * 压缩（缺 zstd 的用例 SKIP，不 FAIL）。
 *
 * 覆盖（契约逐块）：
 * - workflows[]：跨模板分组、tickets/elapsed_ms/stage_runs/rounds_per_ticket、
 *   rounds 缺失票剔出分母 + notice（缺绝不折算 0）。
 * - stages[]：(workflow, stage) 键不混链、runs/avg_rounds_per_ticket 分母=
 *   reached 票、elapsed_ms。
 * - project_sessions：executor/global 桶、票形目录剔除、畸形/坏会话文件 reason、
 *   无项目级会话 → 整块 null + reason、tokens_outside_tickets 跟随。
 * - kpis 加性字段：rework_rate / throughput_per_day / median_lead_time /
 *   human_wait_share / tokens_in_tickets / tokens_per_closed_ticket / cache_hit。
 * - epics[]：tickets/elapsed_ms/tokens/last_activity_ms、无 token 票的 epic
 *   tokens=null+reason、窗口无 epic → null+notice。
 * - health 视图：v2 块恒 null + reason（具名降级）。
 * - fast 与 full 缓存预热后聚合一致（非空比较防 vacuous green）。
 */
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents, ok as libOk, summary, dumpFails } from './lib.mjs'

// Main-module guard: importing this file must be side-effect-free (merge_check
// imports every tests/*.mjs as a module). Execute the battery only when run
// directly: `node server/plugins/workbench/tests/metrics-v2-blocks.mjs`.
const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href

// lib.ok 的签名是 (name, cond, detail)；本文件按 (cond, label, detail) 书写——此处适配。
function ok(cond, label, detail = '') { libOk(label, cond, detail) }
function section(t) { console.log(`\n== ${t}`) }

async function runAll() {
  const HAS_ZSTD = (() => {
    try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }); return true } catch { return false }
  })()

  /** 自由 slug 的会话 fixture（lib.makeSession 钉死 slug0，不适用桶命名用例）。 */
  function makeSessionSlug(wsRoot, slug, sub, events) {
    if (!HAS_ZSTD) return { ok: false }
    try {
      const sess = join(wsRoot, '.dsh', 'sessions', slug, sub)
      mkdirSync(sess, { recursive: true })
      const raw = join(wsRoot, 'raw.jsonl')
      writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
      execFileSync('zstd', ['-f', '-q', raw, '-o', join(sess, 'session.jsonl.zstd')])
      rmSync(raw)
      return { ok: true }
    } catch (err) {
      return { ok: false, reason: String(err?.message ?? err) }
    }
  }

  const T0 = Date.parse('2026-08-29T01:00:00Z')
  const H = 3600e3

  /** closed 票行（列表行即 show 全文——stub 的 find 直接返回它，timeline 自带）。 */
  function ticket(id, opts = {}) {
    const wf = opts.workflow ?? 'dev-lane'
    const t0 = opts.t0 ?? T0
    const closedAt = opts.closedAt ?? Date.parse('2026-08-30T06:00:00Z')
    const tl = opts.timeline ?? [
      { at: new Date(t0).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(t0 + H).toISOString(), stage: 'review', state: 'running' },
      { at: new Date(t0 + 2 * H).toISOString(), stage: 'implement', state: 'running' },
      { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' },
    ]
    return {
      id, project: 'demo', epic: opts.epic ?? 'metrics', title: id, workflow: wf,
      stage: 'implement', stage_state: opts.status === 'closed' ? 'closed' : 'running',
      status: opts.status ?? 'closed', role: 'developer',
      updated: new Date(opts.updated ?? closedAt).toISOString(),
      worktree: opts.worktree ?? `.worktrees/${id}`,
      ...(opts.noTimeline ? {} : { timeline: tl }),
    }
  }

  const CHORE_STAGES = [{ id: 'chore', role: 'developer', exit: 'agent' }]

  async function runMetrics(m, env) {
    const old = {}
    for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR', 'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']) {
      old[k] = process.env[k]
      delete process.env[k]
    }
    Object.assign(process.env, env)
    try {
      const deps = m.defaultDeps(env.repo, () => NOW)
      const params = { view: env.view ?? 'time', window: '7d', epic: 'all', template: 'dev-lane', mode: env.mode ?? 'full' }
      // project 缺参=后端默认项目（传 '' 会触发「同名参数给出」防穿，与 HTTP 面一致）
      return await m.buildMetricsResponse(params, deps)
    } finally {
      for (const k of Object.keys(old)) {
        if (old[k] === undefined) delete process.env[k]
        else process.env[k] = old[k]
      }
    }
  }

  /* ------------------------------------------------------------ A. 主口径：双模板 + rework + 桶 */

  const repo = freshDir('v2-repo-')
  mkdirSync(join(repo, '.worktrees'), { recursive: true })
  const stubDir = freshDir('v2-stub-')

  // t1：rework（plan 两次）；t2：无 rework；t3：chore-lane 在制；t4：closed 但无 timeline（历史不可读）
  const t1 = ticket('t260921-01', {
    timeline: [
      { at: new Date(T0).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(T0 + H).toISOString(), stage: 'review', state: 'running' },
      { at: new Date(T0 + 2 * H).toISOString(), stage: 'plan', state: 'running' }, // rework 重入
      { at: new Date(T0 + 3 * H).toISOString(), stage: 'implement', state: 'running' },
      { at: new Date(Date.parse('2026-08-30T06:00:00Z')).toISOString(), stage: 'implement', state: 'closed' },
    ],
  })
  const t2 = ticket('t260921-02')
  const t3 = ticket('t260921-03', { workflow: 'chore-lane', status: 'open', epic: 'metrics' })
  const t4 = ticket('t260921-04', { noTimeline: true })

  const stub = baseStub({
    tickets: [t1, t2, t3, t4],
    workflows: [
      { id: 'dev-lane', name: 'dev-lane', lane: 'lane', stages: [
        { id: 'plan', role: 'planner', exit: 'agent' },
        { id: 'review', role: 'reviewer', exit: 'human' },
        { id: 'implement', role: 'developer', exit: 'agent' },
      ] },
      { id: 'chore-lane', name: 'chore-lane', lane: 'lane', stages: CHORE_STAGES },
    ],
  })
  const stubPath = writeStub(stubDir, stub)
  const cacheDir = freshDir('v2-cache-')

  // 会话 fixture：t1 有 token；t2 无（SKIP 面）；项目级 executor/global 桶
  let haveSessions = true
  if (HAS_ZSTD) {
    {
      const ws = join(repo, '.worktrees', 't260921-01')
      mkdirSync(ws, { recursive: true })
      haveSessions = makeSessionSlug(ws, 'slug0', 't260921-01-developer', usageEvents()).ok && haveSessions
    }
    const projEv = [
      { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
      { type: 'assistant/message', data: { usage: { inputTokens: 7, outputTokens: 3, cacheReadTokens: 1 } }, time: 2 },
    ]
    haveSessions = makeSessionSlug(repo, 'executor', 'manual-1', projEv).ok && haveSessions
    haveSessions = makeSessionSlug(repo, 'global', 'ops-1', projEv).ok && haveSessions
    // 票形目录：必须被剔除（不并入 project_sessions）
    makeSessionSlug(repo, 'executor', 't260921-01-developer', projEv)
    // 畸形：伪 zstd 垃圾文件（不入桶数字，reason 浮出）
    mkdirSync(join(repo, '.dsh', 'sessions', 'executor', 'garbage-1'), { recursive: true })
    writeFileSync(join(repo, '.dsh', 'sessions', 'executor', 'garbage-1', 'session.jsonl.zstd'), 'not-zstd-at-all')
  }

  const m = await loadMetrics()
  const env = { SANDBAR_METRICS_STUB: stubPath, SANDBAR_METRICS_DIR: cacheDir, repo }

  section('A. workflows[] / stages[]：跨模板分组 + rounds')
  let r = (await runMetrics(m, env)).body
  ok(r.cache.source_version === 'v3', 'source_version bump 到 v3', r.cache?.source_version)
  ok(Array.isArray(r.workflows) && r.workflows.length === 2, 'workflows 两模板各一条', JSON.stringify(r.workflows))
  const wfDev = r.workflows.find((w) => w.workflow === 'dev-lane')
  const wfChore = r.workflows.find((w) => w.workflow === 'chore-lane')
  ok(wfDev && wfDev.tickets === 2, 'dev-lane tickets=2（t4 无锚不入窗，契约单锚归窗）', JSON.stringify(wfDev))
  ok(wfChore && wfChore.tickets === 1, 'chore-lane tickets=1（t3，链条未混入 dev-lane）')
  ok(wfDev.stage_runs === 7, 'dev-lane stage_runs=7（t1: plan2+review1+impl1=4 rework 计入；t2: 3）', JSON.stringify(wfDev))
  ok(wfDev.rounds_per_ticket === 3.5, 'dev-lane rounds_per_ticket=7/2=3.5', JSON.stringify(wfDev?.rounds_per_ticket))
  const planRow = (r.stages ?? []).find((s) => s.workflow === 'dev-lane' && s.stage === 'plan')
  ok(planRow && planRow.runs === 3 && planRow.avg_rounds_per_ticket === 1.5, 'stages plan: runs=3, avg=3/2=1.5', JSON.stringify(planRow))
  ok((r.stages ?? []).every((s) => typeof s.workflow === 'string' && typeof s.stage === 'string'), 'stages 行键=(workflow, stage) 双键')

  section('B. project_sessions：桶 + 票形剔除 + 畸形文件')
  const ps = r.project_sessions
  if (!HAS_ZSTD) {
    ok(ps === null && typeof r.reason === 'string' && r.reason.length > 0, '无 zstd 环境：块 null + reason（SKIP 语义）')
  } else if (haveSessions) {
    ok(ps !== null && typeof ps === 'object', 'project_sessions 块在场')
    ok(ps.buckets?.executor && ps.buckets?.global, 'executor/global 两桶在场', JSON.stringify(ps?.buckets))
    ok(ps.buckets.executor.in === 7 && ps.buckets.executor.out === 3 && ps.buckets.executor.files === 2, 'executor 桶=manual-1 好数据 + garbage 计 0（票形目录已剔除，坏文件不炸桶）', JSON.stringify(ps.buckets?.executor))
    ok(ps.total && ps.total.in === 14 && ps.total.out === 6 && ps.total.cache_read === 2, 'total=executor+global 合计', JSON.stringify(ps.total))
    ok(typeof ps.reason === 'string' && ps.reason.length > 0, '坏文件 reason 浮出（不静默）', JSON.stringify(ps.reason))
    ok(r.kpis.tokens_outside_tickets === 20, 'kpis.tokens_outside_tickets=in+out=20', JSON.stringify(r.kpis.tokens_outside_tickets))
  } else {
    ok(false, 'zstd 在但会话 fixture 失败（环境问题）')
  }

  section('C. kpis 加性字段')
  const k = r.kpis
  ok(k.closed === 2, 'closed=2（t1/t2；t4 无锚不入窗人口）', JSON.stringify(k))
  ok(k.rework_rate === 0.5, 'rework_rate=1/2（t4 无历史剔出分母）', JSON.stringify(k.rework_rate))
  ok(typeof k.median_lead_time === 'number' && k.median_lead_time === Date.parse('2026-08-30T06:00:00Z') - T0, 'median_lead_time=t1 lead（t4 无锚不取）', JSON.stringify(k.median_lead_time))
  ok(typeof k.throughput_per_day === 'number' && k.throughput_per_day > 0, 'throughput_per_day>0', JSON.stringify(k.throughput_per_day))
  ok(k.human_wait_share !== null && k.human_wait_share > 0 && k.human_wait_share < 1, 'human_wait_share∈(0,1)', JSON.stringify(k.human_wait_share))
  if (HAS_ZSTD && haveSessions) {
    ok(k.tokens_in_tickets === 110, 'tokens_in_tickets=110（t1 会话 in100+out10）', JSON.stringify(k.tokens_in_tickets))
    ok(k.tokens_per_closed_ticket === 55, 'tokens_per_closed_ticket=110/2', JSON.stringify(k.tokens_per_closed_ticket))
    ok(Math.abs(k.cache_hit - 5 / 115) < 1e-4, 'cache_hit=5/115（chunk 镜像未翻倍）', JSON.stringify(k.cache_hit))
    ok(typeof r.reason === 'string' && r.reason.length > 0, '坏会话文件使响应带 reason（具名降级）', String(r.reason))
  }

  section('C2. rounds 缺失语义（computeDurations 单元面）：缺历史≠0')
  {
    const d = m.computeDurations(undefined, new Set(), NOW)
    ok(d.history_ok === false && Object.keys(d.runs).length === 0, 'timeline 缺失：history_ok=false（rounds 未知，非 0）', JSON.stringify({ history_ok: d.history_ok, runs: d.runs }))
    const d2 = m.computeDurations([
      { at: new Date(T0).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(T0 + H).toISOString(), stage: 'plan', state: 'running' },
    ], new Set(), NOW)
    ok(d2.runs.plan === 2, '同 stage 两次 running：runs=2（rework 计入）', JSON.stringify(d2.runs))
  }

  section('D. epics[]')
  ok(Array.isArray(r.epics) && r.epics.length === 1, 'epics 一条（metrics）', JSON.stringify(r.epics))
  const ep = r.epics?.[0]
  ok(ep && ep.tickets === 3, 'epic tickets=3（窗口人口 t1/t2/t3）')
  if (HAS_ZSTD && haveSessions) ok(ep.tokens === 110, 'epic tokens=110（无 token 票不炸聚合）', JSON.stringify(ep?.tokens))
  ok(ep && ep.last_activity_ms === Date.parse(t3.updated), 'last_activity_ms=最新 updated（t3）', JSON.stringify(ep?.last_activity_ms))

  section('E. 具名降级：无项目级会话 / 无 epic / health')
  {
    const emptyRepo = freshDir('v2-empty-')
    // 独立缓存目录：防前一段的 t1 token 缓存命中把「无会话」降级污染成 110
    const env2 = { ...env, repo: emptyRepo, SANDBAR_METRICS_DIR: freshDir('v2-cache2-') }
    const r2 = (await runMetrics(m, env2)).body
    ok(r2.project_sessions === null, '无项目级会话：project_sessions=null', JSON.stringify(r2.project_sessions))
    ok(r2.kpis.tokens_outside_tickets === null, 'tokens_outside_tickets 跟随 null（不零填）')
    ok(Array.isArray(r2.epics) && r2.epics[0]?.tokens === null && typeof r2.epics[0]?.reason === 'string', '无 token 票的 epic：tokens=null+reason', JSON.stringify(r2.epics))
    const r3 = (await runMetrics(m, { ...env2, view: 'health' })).body
    ok(r3.workflows === null && r3.stages === null && r3.project_sessions === null && r3.epics === null, 'health：v2 块恒 null')
    ok(typeof r3.reason === 'string' && r3.reason.includes('not in the health direct-query path'), 'health 降级 reason 具名', r3.reason)
    ok(r3.kpis.rework_rate === null && r3.kpis.median_lead_time === null, 'health：加性 kpi 恒 null')
  }

  section('F. fast 与 full 缓存预热后聚合一致')
  {
    const full = (await runMetrics(m, { ...env, mode: 'full' })).body
    const fast = (await runMetrics(m, { ...env, mode: 'fast' })).body
    ok(full.workflows?.length > 0 && JSON.stringify(full.workflows) === JSON.stringify(fast.workflows), 'workflows fast==full（缓存预热，非空比较防 vacuous green）')
    ok(full.stages?.length > 0 && JSON.stringify(full.stages) === JSON.stringify(fast.stages), 'stages fast==full（非空比较）')
    ok(JSON.stringify(full.kpis) === JSON.stringify(fast.kpis), 'kpis fast==full')
  }


}

if (__isMain) {
  await runAll()
} else {
  // Imported as a module: no side effects, no process.exit. Nothing is asserted.
  console.log('metrics-v2-blocks: imported as a module; battery skipped (run the file directly to execute)')
}
