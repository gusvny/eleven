/**
 * tests/t261025-14-archived-usage.mjs —— 闭票 token 治愈单测（t261025-14）。
 *
 * 直跑：node server/plugins/workbench/tests/t261025-14-archived-usage.mjs
 * 全桩化（SANDBAR_METRICS_STUB + SANDBAR_METRICS_DIR 临时目录），零真实
 * ~/.sandbar / admin.py / git 触碰；会话 fixture 用系统 zstd 现场压缩（缺 zstd 的
 * 用例 SKIP，不 FAIL）。
 *
 * 覆盖（方案 + review 三条件）：
 * - 归档缝：泳道无会话、M1-3 归档 (<metrics-dir>/<key>/data/tickets/<id>/sessions/)
 *   有会话 → 闭票 tokens 从归档算出（先无档跑一拍落 null 缓存，再加档治愈——
 *   钉死条件 C 的缓存命中放行），治愈票仍在窗内（F1 锚点纪律不被治愈破坏）。
 * - aggregate-all 钉死：同一归档票两个角色目录 → 两份都入统计（防 newest-only
 *   回潮丢角色）。
 * - 代理文件/坏件不静默：好 zstd + 文本假 zstd（archive_ticket 0 字节代理文件
 *   同形态）→ 好件照常入统计，suspect 独立浮出（reason 可分辨「存在但解不开」）。
 * - 防穿：projectKey / ticketId 越界形状 → refused（单元级直调）。
 * - 票外面具名：project_sessions 缺 → tokens_outside_tickets=null + notice 点名
 *   「总量只盖票内」；票外只有 cacheRead → 面值 0 非 null。
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents, ok as libOk, summary } from './lib.mjs'

const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href

function ok(cond, label, detail = '') { libOk(label, cond, detail) }
function section(t) { console.log(`\n== ${t}`) }

async function runAll() {
  const HAS_ZSTD = (() => {
    try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }); return true } catch { return false }
  })()

  /** 往归档 sessions 目录压一份会话（root=<metrics-dir>，key=demo）。 */
  function archiveSession(metricsDir, ticketId, role, events, fileName = 'session.jsonl.zstd') {
    if (!HAS_ZSTD) return { ok: false }
    try {
      const sess = join(metricsDir, 'demo', 'data', 'tickets', ticketId, 'sessions', 'slug0', `${ticketId}-${role}`)
      mkdirSync(sess, { recursive: true })
      const raw = join(metricsDir, 'raw.jsonl')
      writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
      execFileSync('zstd', ['-f', '-q', raw, '-o', join(sess, fileName)])
      rmSync(raw)
      return { ok: true, dir: sess }
    } catch (err) {
      return { ok: false, reason: String(err?.message ?? err) }
    }
  }

  function closedTicketRow(id, closedAt = Date.parse('2026-08-30T06:00:00Z'), t0 = Date.parse('2026-08-29T01:00:00Z')) {
    return {
      id, project: 'demo', epic: 'metrics', title: id, workflow: 'dev-lane',
      stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
      updated: new Date(closedAt).toISOString(),
      worktree: `.worktrees/${id}`,
      timeline: [
        { at: new Date(t0).toISOString(), stage: 'plan', state: 'running' },
        { at: new Date(t0 + 3600e3).toISOString(), stage: 'review', state: 'running' },
        { at: new Date(t0 + 2 * 3600e3).toISOString(), stage: 'implement', state: 'running' },
        { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' },
      ],
    }
  }

  async function runMetrics(m, env) {
    const old = {}
    for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR', 'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']) {
      old[k] = process.env[k]
      delete process.env[k]
    }
    Object.assign(process.env, env)
    try {
      const deps = m.defaultDeps(env.repo, () => NOW)
      const params = { view: env.view ?? 'time', window: '7d', epic: 'all', template: 'dev-lane', mode: 'full' }
      return await m.buildMetricsResponse(params, deps)
    } finally {
      for (const k of Object.keys(old)) {
        if (old[k] === undefined) delete process.env[k]
        else process.env[k] = old[k]
      }
    }
  }

  /* ------------------------------------------ A. 归档缝 + 条件 C 治愈 + 窗内锚点 */

  section('A. closed ticket healed from the M1-3 archive (condition C)')
  const repoA = freshDir('t26102514-repo-a-')
  mkdirSync(join(repoA, '.worktrees'), { recursive: true })
  const stubDirA = freshDir('t26102514-stub-a-')
  const metricsDirA = freshDir('t26102514-metrics-a-')
  const tA = 't260830-01'
  writeStub(stubDirA, baseStub({ tickets: [closedTicketRow(tA)] }))
  const envA = {
    repo: repoA,
    SANDBAR_METRICS_STUB: join(stubDirA, 'stub.json'),
    SANDBAR_METRICS_DIR: metricsDirA,
  }

  // 第一拍：无泳道会话、无账本、无归档 → tokens=null（存量行为），票外=null 且点名
  const r1 = await runMetrics(m, envA)
  ok(r1.status === 200, 'A1 first pass status 200', JSON.stringify(r1.body?.kpis ?? r1))
  ok(r1.body.kpis.tokens_in_tickets === null, 'A2 no archive -> tokens_in_tickets null', String(r1.body.kpis.tokens_in_tickets))
  ok(r1.body.kpis.tokens_outside_tickets === null, 'A3 no project sessions -> tokens_outside_tickets null')
  const coverNotice = String(r1.body.reason ?? '').includes('cover tickets only')
  ok(coverNotice, 'A4 tickets-only caliber named in the face reason', String(r1.body.reason ?? '').slice(0, 200))
  ok(existsSync(join(metricsDirA, 'demo', 'data', 'metrics', `${tA}.json`)), 'A5 cache record written with tokens null')
  const cached1 = JSON.parse(readFileSync(join(metricsDirA, 'demo', 'data', 'metrics', `${tA}.json`), 'utf8'))
  ok(cached1.tokens === null, 'A6 cached record carries tokens null', String(cached1.tokens))

  // 第二拍：归档有会话 → 条件 C 放行治愈，tokens 从归档算出
  const madeA = archiveSession(metricsDirA, tA, 'developer', usageEvents())
  if (!madeA.ok) { summary('t261025-14-archived-usage (SKIP: no zstd)'); return }
  const r2 = await runMetrics(m, envA)
  ok(r2.status === 200, 'A7 heal pass status 200')
  ok(r2.body.kpis.tokens_in_tickets === 110, 'A8 healed tokens_in_tickets = in100+out10', String(r2.body.kpis.tokens_in_tickets))
  ok(r2.body.kpis.closed >= 1, 'A9 healed record stays in-window (closed count keeps the ticket)', String(r2.body.kpis.closed))
  const cached2 = JSON.parse(readFileSync(join(metricsDirA, 'demo', 'data', 'metrics', `${tA}.json`), 'utf8'))
  ok(cached2.tokens !== null && cached2.tokens.in === 100, 'A10 cache record healed to tokens non-null', JSON.stringify(cached2.tokens))
  ok(cached2.computed_at === cached1.computed_at, 'A11 anchor base preserved across heal (F1 discipline)', `${cached1.computed_at} -> ${cached2.computed_at}`)

  /* ------------------------------------------ B. aggregate-all（双角色目录都入统计） */

  section('B. aggregate-all: two archived role dirs both counted')
  const repoB = freshDir('t26102514-repo-b-')
  mkdirSync(join(repoB, '.worktrees'), { recursive: true })
  const stubDirB = freshDir('t26102514-stub-b-')
  const metricsDirB = freshDir('t26102514-metrics-b-')
  const tB = 't260830-02'
  writeStub(stubDirB, baseStub({ tickets: [closedTicketRow(tB)] }))
  archiveSession(metricsDirB, tB, 'developer', usageEvents())
  archiveSession(metricsDirB, tB, 'reviewer', usageEvents())
  const rB = await runMetrics(m, { repo: repoB, SANDBAR_METRICS_STUB: join(stubDirB, 'stub.json'), SANDBAR_METRICS_DIR: metricsDirB })
  ok(rB.body.kpis.tokens_in_tickets === 220, 'B1 two role dirs both aggregated (2 x 110)', String(rB.body.kpis.tokens_in_tickets))

  /* ------------------------------------------ C. 代理文件/坏件不静默 */

  section('C. proxy-file (text posing as zstd) named, never silently dropped')
  const repoC = freshDir('t26102514-repo-c-')
  mkdirSync(join(repoC, '.worktrees'), { recursive: true })
  const stubDirC = freshDir('t26102514-stub-c-')
  const metricsDirC = freshDir('t26102514-metrics-c-')
  const tC = 't260830-03'
  writeStub(stubDirC, baseStub({ tickets: [closedTicketRow(tC)] }))
  archiveSession(metricsDirC, tC, 'developer', usageEvents())
  const proxyDir = archiveSession(metricsDirC, tC, 'reviewer', []).dir
  // 0 字节源在 archive_ticket 里被改写为中文代理文件——同形态：扩展名 .jsonl.zstd 但内容是文本
  writeFileSync(join(proxyDir, 'session.jsonl.zstd'), '代理文件：本泳道归档时 .dsh/sessions/... 不存在\n')
  const u = await import(new URL('./../src/host/agent-usage.ts', import.meta.url).pathname)
  const arcC = await u.resolveArchivedSessionFiles(metricsDirC, 'demo', tC)
  ok(arcC.paths.length === 2, 'C1 both archived files discovered', JSON.stringify(arcC.paths))
  const aggC = await u.aggregateTicketUsage(arcC.paths, [])
  // 代理文件形态：文件在、zstd 解不开 → 走「跳过并记原因」面（非 S1 judge 面）。
  // 钉死 review 条件 1：坏件原因在好件入账时也不被吞（reason 可分辨「存在但解不开」）。
  ok(aggC.total.input === 100, 'C2 totals still come from the good file', JSON.stringify(aggC.total))
  ok(typeof aggC.reason === 'string' && aggC.reason.length > 0
    && (aggC.reason.includes('解压') || aggC.reason.includes('格式') || aggC.reason.includes(decodeURIComponent('fail'))),
  'C3 undecodable proxy file named in reason while exists=true', aggC.reason)

  /* ------------------------------------------ D. 防穿（单元级直调） */

  section('D. traversal shapes refused')
  const d1 = await u.resolveArchivedSessionFiles(freshDir('t26102514-root-'), '../evil', tA)
  ok(d1.refused === true && d1.paths.length === 0, 'D1 traversal projectKey refused', JSON.stringify(d1))
  const d2 = await u.resolveArchivedSessionFiles(freshDir('t26102514-root-'), 'demo', '../../etc/passwd')
  ok(d2.refused === true && d2.paths.length === 0, 'D2 traversal ticketId refused', JSON.stringify(d2))

  /* ------------------------------------------ E. 票外只有 cacheRead → 面值 0 非 null */

  section('E. ticket-external cache-only session: face shows 0, never null')
  const repoE = freshDir('t26102514-repo-e-')
  mkdirSync(join(repoE, '.worktrees'), { recursive: true })
  const stubDirE = freshDir('t26102514-stub-e-')
  const metricsDirE = freshDir('t26102514-metrics-e-')
  writeStub(stubDirE, baseStub({ tickets: [] }))
  const sessE = join(repoE, '.dsh', 'sessions', 'executor', 'adhoc-run')
  mkdirSync(sessE, { recursive: true })
  const rawE = join(repoE, 'raw.jsonl')
  writeFileSync(rawE, JSON.stringify({ type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 }) + '\n'
    + JSON.stringify({ type: 'assistant/message', data: { usage: { inputTokens: 0, outputTokens: 0, cacheReadTokens: 100 } }, time: 2 }) + '\n')
  execFileSync('zstd', ['-f', '-q', rawE, '-o', join(sessE, 'session.jsonl.zstd')])
  rmSync(rawE)
  const rE = await runMetrics(m, { repo: repoE, SANDBAR_METRICS_STUB: join(stubDirE, 'stub.json'), SANDBAR_METRICS_DIR: metricsDirE })
  ok(rE.body.kpis.tokens_outside_tickets === 0, 'E1 cache-only external session -> 0 (explicit null check)', String(rE.body.kpis.tokens_outside_tickets))

  summary('t261025-14-archived-usage')
}

const m = await loadMetrics()
if (__isMain) {
  await runAll()
} else {
  console.log('[t261025-14-archived-usage] imported as module; battery skipped (run directly)')
}
