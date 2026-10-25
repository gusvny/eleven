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
      // engine row shape: updated_ts is epoch SECONDS (t261025-13: the only field the
      // metrics read path may use as a timestamp; `updated` is a display string)
      updated_ts: Math.round((opts.updatedTsMs ?? (opts.updated ?? closedAt)) / 1000),
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
    // t261025-13 token-coverage inputs (panel's over-N-of-M lines)
    ok(k.tokens_cache_read === 5 && k.tickets_with_usage === 1 && k.closed_with_usage === 1,
      'coverage inputs: cacheRead=5, tickets_with_usage=1, closed_with_usage=1', JSON.stringify({ cr: k.tokens_cache_read, twu: k.tickets_with_usage, cwu: k.closed_with_usage }))
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
  ok(ep && ep.last_activity_ms === t3.updated_ts * 1000, 'last_activity_ms=最新 updated_ts（t3，机器字段秒→ms）', JSON.stringify(ep?.last_activity_ms))

  section('E. 具名降级：无项目级会话 / 无 epic / health')
  {
    const emptyRepo = freshDir('v2-empty-')
    // 独立缓存目录：防前一段的 t1 token 缓存命中把「无会话」降级污染成 110
    const env2 = { ...env, repo: emptyRepo, SANDBAR_METRICS_DIR: freshDir('v2-cache2-') }
    const r2 = (await runMetrics(m, env2)).body
    ok(r2.project_sessions === null, '无项目级会话：project_sessions=null', JSON.stringify(r2.project_sessions))
    ok(r2.kpis.tokens_outside_tickets === null, 'tokens_outside_tickets 跟随 null（不零填）')
    ok(Array.isArray(r2.epics) && r2.epics[0]?.tokens === null && typeof r2.epics[0]?.reason === 'string', '无 token 票的 epic：tokens=null+reason', JSON.stringify(r2.epics))
    ok(r2.kpis.tokens_cache_read === null && r2.kpis.tickets_with_usage === null && r2.kpis.closed_with_usage === null,
      'coverage inputs null on a no-token-data window (never 0-filled)', JSON.stringify({ cr: r2.kpis.tokens_cache_read, twu: r2.kpis.tickets_with_usage, cwu: r2.kpis.closed_with_usage }))
    const r3 = (await runMetrics(m, { ...env2, view: 'health' })).body
    ok(r3.workflows === null && r3.stages === null && r3.project_sessions === null && r3.epics === null, 'health：v2 块恒 null')
    ok(typeof r3.reason === 'string' && r3.reason.includes('not in the health direct-query path'), 'health 降级 reason 具名', r3.reason)
    ok(r3.kpis.rework_rate === null && r3.kpis.median_lead_time === null, 'health：加性 kpi 恒 null')
  }

  section('E2. role_aggregate (t261026-02): per-role faces / named empty roles / ticket-shaped no-role skips / bad files')
  {
    // Main repo: executor/t260921-01-developer is a ticket-shaped dir (carries a developer session).
    if (HAS_ZSTD && haveSessions) {
      const ra = r.role_aggregate
      ok(ra && typeof ra === 'object' && typeof ra.searched === 'string' && ra.searched.endsWith(join('.dsh', 'sessions')), 'role_aggregate present with searched root', JSON.stringify(ra?.searched))
      ok(ra.roles?.developer && ra.roles.developer.in === 7 && ra.roles.developer.out === 3 && ra.roles.developer.cache_read === 1, 'developer face in=7/out=3/cache=1 (ticket-shaped dir aggregated)', JSON.stringify(ra.roles?.developer))
      ok(ra.roles.developer.tickets === 1, 'developer tickets=1 (t260921-01)')
      ok(ra.total && ra.total.in === 7, 'role total.in=7 (single role)', JSON.stringify(ra.total))
    }
    // Dedicated repo: integration has a session (plus a bad one); executor has only a bad file;
    // t1-2x-old is ticket-shaped with no parseable role -> named skip, never folded.
    const raRepo = freshDir('v2-ra-')
    mkdirSync(join(raRepo, '.worktrees'), { recursive: true })
    const raEv = [
      { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
      { type: 'assistant/message', data: { usage: { inputTokens: 7, outputTokens: 3, cacheReadTokens: 1 } }, time: 2 },
    ]
    if (HAS_ZSTD) {
      makeSessionSlug(raRepo, 'slug9', 't260926-01-integration', raEv)
      mkdirSync(join(raRepo, '.dsh', 'sessions', 'slug9', 't260926-02-executor'), { recursive: true })
      writeFileSync(join(raRepo, '.dsh', 'sessions', 'slug9', 't260926-02-executor', 'session.jsonl.zstd'), 'not-zstd-at-all')
    }
    mkdirSync(join(raRepo, '.dsh', 'sessions', 'slug9', 't1-2x-old'), { recursive: true })
    const ra = (await runMetrics(m, { ...env, repo: raRepo, SANDBAR_METRICS_DIR: freshDir('v2-cache3-') })).body.role_aggregate
    if (!HAS_ZSTD) {
      ok(ra && ra.roles && Object.keys(ra.roles).length === 0 && typeof ra.reason === 'string', 'no zstd: roles empty + reason (SKIP semantics)')
    } else {
      ok(ra.roles?.integration && ra.roles.integration.in === 7 && ra.roles.integration.tickets === 1, 'integration face present', JSON.stringify(ra.roles))
      ok(ra.roles?.executor && ra.roles.executor.files === 1 && ra.roles.executor.in === 0 && typeof ra.roles.executor.reason === 'string', 'executor file present but bad: files=1/zeros + per-file reason (not "no sessions")', JSON.stringify(ra.roles?.executor))
      ok(ra.roles?.developer === undefined, 'developer has no sessions: role absent (UI says no sessions in window, role never invented)')
      ok(typeof ra.reason === 'string' && ra.reason.includes('t1-2x-old') && ra.reason.includes('no role parsed'), 'ticket-shaped role-less dir named as a skip (never silently folded)', JSON.stringify(ra.reason))
    }
    // Empty repo: whole block empty + reason; project_sessions degrade travels structured.
    const emptyRepo2 = freshDir('v2-ra-empty-')
    mkdirSync(join(emptyRepo2, '.worktrees'), { recursive: true })
    const r2b = (await runMetrics(m, { ...env, repo: emptyRepo2, SANDBAR_METRICS_DIR: freshDir('v2-cache4-') })).body
    ok(r2b.role_aggregate && Object.keys(r2b.role_aggregate.roles).length === 0 && typeof r2b.role_aggregate.reason === 'string', 'empty repo: role_aggregate roles empty + reason', JSON.stringify(r2b.role_aggregate))
    ok(r2b.project_sessions_degrade && typeof r2b.project_sessions_degrade.reason === 'string' && typeof r2b.project_sessions_degrade.searched === 'string', 'null block reason+searched carried structured (not only in notices)', JSON.stringify(r2b.project_sessions_degrade))
    ok(typeof r2b.project_sessions_home_candidate === 'string' && r2b.project_sessions_home_candidate.includes('.dsh'), 'DSH home candidate root named (named only, never read)', JSON.stringify(r2b.project_sessions_home_candidate))
    const r3b = (await runMetrics(m, { ...env, repo: emptyRepo2, view: 'health' })).body
    ok(r3b.role_aggregate && Object.keys(r3b.role_aggregate.roles ?? {}).length === 0 && String(r3b.role_aggregate.reason).includes('health direct-query path'), 'health: role_aggregate empty + health-path reason (object shape kept)', JSON.stringify(r3b.role_aggregate))
    ok(r3b.project_sessions_degrade && typeof r3b.project_sessions_degrade.reason === 'string', 'health: structured project_sessions degrade', JSON.stringify(r3b.project_sessions_degrade))
  }

  section('F. fast 与 full 缓存预热后聚合一致')
  {
    const full = (await runMetrics(m, { ...env, mode: 'full' })).body
    const fast = (await runMetrics(m, { ...env, mode: 'fast' })).body
    ok(full.workflows?.length > 0 && JSON.stringify(full.workflows) === JSON.stringify(fast.workflows), 'workflows fast==full（缓存预热，非空比较防 vacuous green）')
    ok(full.stages?.length > 0 && JSON.stringify(full.stages) === JSON.stringify(fast.stages), 'stages fast==full（非空比较）')
    ok(JSON.stringify(full.kpis) === JSON.stringify(fast.kpis), 'kpis fast==full')
  }

  /* ------------------------------------------ G. t261025-13：展示列永不决定时间戳 */

  {
    // Regression for the fabricated year-2001 last_activity_ms: every row below
    // carries a display-shaped `updated` ("10-25 22:17" — V8 parses it as 2001);
    // only the machine field `updated_ts` (epoch seconds) may decide a timestamp.
    const DISPLAY = '10-25 22:17'
    const displayMs = new Date(DISPLAY).getTime() // the invented 2001 value
    const gRepo = freshDir('v2-g-repo-')
    mkdirSync(join(gRepo, '.worktrees'), { recursive: true })
    const gStubDir = freshDir('v2-g-stub-')
    const gCache = freshDir('v2-g-cache-')
    const inWinSec = Math.round((NOW - 3600e3) / 1000) // inside the 7d window
    const oldSec = Math.round((NOW - 10 * 86400e3) / 1000) // outside the 7d window
    const rawRow = (id, extra) => {
      const status = extra.status ?? 'closed'
      return {
      id, project: 'demo', epic: extra.epic ?? 'g', title: id, workflow: 'dev-lane',
      stage: 'implement', stage_state: extra.stage_state ?? status,
      status, role: 'developer',
      updated: DISPLAY, updated_ts: extra.updated_ts,
      worktree: `.worktrees/${id}`, ...(extra.noTimeline ? {} : { timeline: [
        { at: new Date(NOW - 2 * H).toISOString(), stage: 'chore', state: 'running' },
        { at: new Date(NOW - H).toISOString(), stage: 'chore', state: status === 'closed' ? 'closed' : 'running' },
      ] }),
      }
    }
    const gStub = baseStub({
      tickets: [
        rawRow('g1', { updated_ts: inWinSec }), // live-shaped: display + machine field
        rawRow('g2', { updated_ts: 0, epic: 'g2', status: 'open', stage_state: 'running' }), // 0 = missing
        rawRow('g3', { updated_ts: String(inWinSec), epic: 'g3' }), // numeric string coerces
        rawRow('g4', { epic: 'g4', status: 'open', stage_state: 'running' }), // machine field absent
        rawRow('g5', { updated_ts: oldSec, epic: 'g5', status: 'open', stage_state: 'running', noTimeline: true }), // stale running → silent list
      ],
      workflows: [{ id: 'dev-lane', name: 'dev-lane', lane: 'lane', stages: CHORE_STAGES }],
    })
    const gPath = writeStub(gStubDir, gStub)
    const gm = await loadMetrics()
    const gEnv = { SANDBAR_METRICS_STUB: gPath, SANDBAR_METRICS_DIR: gCache, repo: gRepo }

    const gr = (await runMetrics(gm, gEnv)).body
    const byEpic = new Map((gr.epics ?? []).map((e) => [e.epic, e]))
    const g1 = byEpic.get('g')
    ok(g1 && g1.last_activity_ms === inWinSec * 1000, 'G: last_activity_ms=updated_ts 秒→ms（机器字段）', JSON.stringify(g1))
    ok(g1 && g1.last_activity_ms !== displayMs && g1.last_activity_ms > Date.parse('2020-01-01T00:00:00Z'), 'G: 2001 展示列解析值不出现', JSON.stringify({ displayMs, got: g1?.last_activity_ms }))
    const g2 = byEpic.get('g2')
    ok(g2 && g2.last_activity_ms === null && typeof g2.reason === 'string' && g2.reason.includes('unparseable'), 'G: updated_ts=0 → null+reason（不零填不编造）', JSON.stringify(g2))
    const g3 = byEpic.get('g3')
    ok(g3 && g3.last_activity_ms === inWinSec * 1000, 'G: 数字串 updated_ts 容错换算', JSON.stringify(g3))
    const g4 = byEpic.get('g4')
    ok(g4 && g4.last_activity_ms === null, 'G: 机器字段缺失 → null（display updated 顶不上）', JSON.stringify(g4))
    ok(gr.kpis.p90_lead_time !== null && gr.kpis.p90_lead_time >= gr.kpis.median_lead_time, "G: p90_lead_time 在场且 >= median", JSON.stringify({ p90: gr.kpis.p90_lead_time, median: gr.kpis.median_lead_time }))

    // health 直查路径：归窗锚 + 静默在制都吃 updated_ts（改前吃 2001 展示列）
    const hr = (await runMetrics(gm, { ...gEnv, view: 'health' })).body
    ok(hr.kpis.tickets === 2 && hr.kpis.closed === 2, 'G health: 7d 归窗按 updated_ts（g1/g3 在窗；g5 落窗外；tickets=closed=2）', JSON.stringify({ tickets: hr.kpis.tickets, closed: hr.kpis.closed }))
    ok(typeof hr.reason === 'string' && hr.reason.includes('updated_ts'), 'G health: 归窗 reason 具名 updated_ts 机器字段', hr.reason)
    // silent-running: g5 (running, stale updated_ts) enters the silent chart; g2
    // (updated_ts=0 → no anchor) and g4 (display-only) do not — both the 2001 false
    // positive and the never-firing gate are sealed.
    const silent = (hr.charts?.secondaries ?? []).find((s) => String(s.title ?? '').startsWith('静默在制'))
    ok(silent && JSON.stringify(silent.categories) === JSON.stringify(['g5']), 'G health: 静默榜只收 updated_ts 超阈的在制票（g5；g2/g4 不进）', JSON.stringify(silent))
  }



}

if (__isMain) {
  await runAll()
} else {
  // Imported as a module: no side effects, no process.exit. Nothing is asserted.
  console.log('metrics-v2-blocks: imported as a module; battery skipped (run the file directly to execute)')
}
