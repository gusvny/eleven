#!/usr/bin/env node
/**
 * t06_concurrency.mjs —— t260902-05⑦ 并发改造单测（node 直跑）。
 *
 * 覆盖（方案 R3 ①，并发改造最易破坏的三个面）：
 *   A. mapPool 保序：乱序完成时结果按入参序落位；并发度上限生效。
 *   B. 串行(env=1)/并发(env=4) 响应一致（同 stub、剔除 generated_at/cache.computed_at
 *      后逐字段一致，四 view 全覆盖）。
 *   C. 错误注入：单票 git 抛错 / showTicket 返回 null / list 行缺 id——并发下
 *      skipped 列表、reason 集、cache.status 语义与串行一致；故障票不拖垮其余票。
 */
import { mkdtemp, rm, writeFile, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { buildMetricsResponse, defaultDeps, mapPool, TICKET_CONCURRENCY } from './../src/host/metrics.ts'

let passed = 0
let failed = 0
function ok(cond, label) { if (cond) { passed++; console.log(`  ok ${label}`) } else { failed++; console.log(`  FAIL ${label}`) } }
function section(t) { console.log(`\n== ${t}`) }

const now = Date.now()
const iso = (ms) => new Date(ms).toISOString()
const day = 86_400_000
const mkTicket = (id, daysAgo, closedAfterHours) => ({
  id, epic: '', workflow: 'dev-lane',
  status: closedAfterHours === null ? 'running' : 'closed',
  timeline: [
    { at: iso(now - daysAgo * day), stage: 'create_plan', state: 'running' },
    { at: iso(now - daysAgo * day + 3600_000), stage: 'implement', state: 'running' },
    ...(closedAfterHours === null ? [] : [{ at: iso(now - daysAgo * day + closedAfterHours * 3600_000), stage: 'implement', state: 'closed' }]),
  ],
  base_ref: 'main', worktree: '',
})

const tmp = await mkdtemp(join(tmpdir(), 'wb-conc-'))
process.env.SANDBAR_METRICS_DIR = join(tmp, 'cache')
await mkdir(process.env.SANDBAR_METRICS_DIR, { recursive: true })

async function withConcurrency(n, fn) {
  const prev = process.env.SANDBAR_METRICS_CONCURRENCY
  process.env.SANDBAR_METRICS_CONCURRENCY = String(n)
  try { return await fn() } finally {
    if (prev === undefined) delete process.env.SANDBAR_METRICS_CONCURRENCY
    else process.env.SANDBAR_METRICS_CONCURRENCY = prev
  }
}

const strip = (body) => JSON.stringify({ ...body, generated_at: '', cache: { ...body.cache, computed_at: '' } })
const runAll = async (deps) => {
  const out = {}
  for (const view of ['time', 'delivery', 'token', 'health'])
    for (const window of ['7d', '30d', 'all']) {
      // 双跑预热（契约 cache.status 语义：冷缓存首门 computed / 次门 hit）——
      // 两模式都取第二跑，比对面不含缓存状态天然差异
      await buildMetricsResponse({ view, window, epic: 'all', template: 'dev-lane' }, deps)
      out[`${view}/${window}`] = strip((await buildMetricsResponse({ view, window, epic: 'all', template: 'dev-lane' }, deps)).body)
    }
  return out
}
const stubDeps = (repo) => defaultDeps(repo) // SANDBAR_METRICS_STUB 由 withStub 注入

async function withStub(stub, fn) {
  const p = join(tmp, `stub-${Math.random().toString(36).slice(2)}.json`)
  await writeFile(p, JSON.stringify(stub))
  process.env.SANDBAR_METRICS_STUB = p
  // t260903-09：宇宙补全（list ∪ 缓存存量）后，各子测试必须用独立缓存目录——
  // 共享目录会把先前子测试的缓存票当 archived 并进当前聚合，污染断言面。
  const prevDir = process.env.SANDBAR_METRICS_DIR
  const cacheRoot = join(tmp, `cache-${Math.random().toString(36).slice(2)}`)
  await mkdir(cacheRoot, { recursive: true })
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  try { return await fn() } finally {
    delete process.env.SANDBAR_METRICS_STUB
    if (prevDir === undefined) delete process.env.SANDBAR_METRICS_DIR
    else process.env.SANDBAR_METRICS_DIR = prevDir
  }
}

try {
  /* A. mapPool 保序 */
  section('A mapPool 保序 + 并发度')
  {
    const r = await mapPool([30, 10, 20], 3, async (v) => { await new Promise(r => setTimeout(r, v)) ; return v * 2 })
    ok(JSON.stringify(r) === '[60,20,40]', `乱序完成按入参序落位（实得 ${JSON.stringify(r)}）`)
    const r2 = await mapPool([1, 2, 3], 0, async v => v)
    ok(JSON.stringify(r2) === '[1,2,3]', '并发度 0 收敛为 1（防呆）')
    ok(TICKET_CONCURRENCY >= 1 && TICKET_CONCURRENCY <= 8, `TICKET_CONCURRENCY 缺省界内（=${TICKET_CONCURRENCY}）`)
    let threw = false
    try { await mapPool([1, 2], 2, async v => { if (v === 2) throw new Error('boom') }) } catch { threw = true }
    ok(threw, '任务抛错整体 reject（与串行 await 链同语义）')
  }

  /* B. 串行/并发一致 */
  section('B 串行(env=1) vs 并发(env=4) 响应一致')
  {
    const stub = {
      project: 'demo', epics: [],
      workflows: [{ id: 'dev-lane', name: 'dev', lane: 'dev', stages: [{ id: 'create_plan' }, { id: 'implement' }, { id: 'review_plan', exit: 'human' }] }],
      tickets: [mkTicket('c-01', 1, 5), mkTicket('c-02', 2, 30), mkTicket('c-03', 0.5, null), mkTicket('c-04', 40, 6)],
      deliveries: {},
    }
    const serial = await withStub(stub, () => withConcurrency(1, () => runAll(stubDeps('/nonexistent'))))
    const par = await withStub(stub, () => withConcurrency(4, () => runAll(stubDeps('/nonexistent'))))
    let same = true
    for (const k of Object.keys(serial)) if (serial[k] !== par[k]) { same = false; console.error(`  不一致 @${k}\n   串行=${serial[k]}\n   并发=${par[k]}`) }
    ok(same && Object.keys(serial).length === 12, '四 view × 三 window 全部一致（12 例）')
  }

  /* C. 错误注入 */
  section('C 错误注入：git 抛错 / showTicket null / 缺 id 行')
  {
    const tickets = [mkTicket('e-01', 1, 5), mkTicket('e-02', 1, 5), mkTicket('e-03', 1, 5)]
    const base = { project: 'demo', epics: [], workflows: [{ id: 'dev-lane', name: 'd', lane: 'dev', stages: [{ id: 'create_plan' }] }], tickets, deliveries: {} }
    // 注入1：git 抛错（delivery 维软降级）——串行 vs 并发 reason/响应一致
    const gitFail = (deps) => ({ ...deps, git: async () => { throw new Error('git 挂了') } })
    const s1 = await withStub(base, () => withConcurrency(1, () => runAll(gitFail(stubDeps('/nonexistent')))))
    const p1 = await withStub(base, () => withConcurrency(3, () => runAll(gitFail(stubDeps('/nonexistent')))))
    let same1 = Object.keys(s1).every(k => s1[k] === p1[k])
    ok(same1, '单票 git 抛错：串行/并发一致（delivery null + reason 同序）')
    ok(s1['delivery/7d'].includes('delivery 维不可算'), 'delivery 失败 reason 人话在场（git 错误经软降级折叠为稳定 reason，见 stableReasons 契约）')
    // 注入2：showTicket 返回 null → 兜底 row（timeline 来自 list 行）
    const showNull = (deps) => ({ ...deps, showTicket: async () => null })
    const s2 = await withStub(base, () => withConcurrency(1, () => runAll(showNull(stubDeps('/nonexistent')))))
    const p2 = await withStub(base, () => withConcurrency(3, () => runAll(showNull(stubDeps('/nonexistent')))))
    ok(Object.keys(s2).every(k => s2[k] === p2[k]), 'showTicket=null：串行/并发一致（兜底 row 语义）')
    ok(JSON.parse(s2['time/7d']).kpis.tickets === 3, '兜底 row 下 KPI 仍计满（不丢票）')
    // 注入3：list 行缺 id → skipped 一条，其余不拖垮
    const withBad = { ...base, tickets: [mkTicket('e-10', 1, 5), { id: '', workflow: 'dev-lane' }, mkTicket('e-11', 1, 5)] }
    const r3 = await withStub(withBad, () => withConcurrency(3, async () => (await buildMetricsResponse({ view: 'time', window: '7d', epic: 'all', template: 'dev-lane' }, stubDeps('/nonexistent'))).body))
    ok(r3.kpis.tickets === 2, `缺 id 行跳过不拖垮（tickets=2，实得 ${r3.kpis.tickets}）`)
    ok(String(r3.reason ?? '').includes('记录生成失败，跳过'), 'skipped reason 在场')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILED'}: ${passed} passed, ${failed} failed`)
process.exit(failed > 0 ? 1 : 0)
