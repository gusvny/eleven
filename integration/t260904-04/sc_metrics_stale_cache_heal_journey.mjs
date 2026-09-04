#!/usr/bin/env node
/**
 * sc_metrics_stale_cache_heal_journey.mjs —— t260904-04 KI-040 L3 旅程场景（灰盒）。
 *
 * intent（用户可感知）：宿主验收原话「t260903-11/12/13、t260904-02 重开面板后交付维
 * 出数；time 与 health 的 closed 计数一致（当前 4 vs 5）」。用户拿着一份算于merge 前
 * /闭单前的陈旧缓存重开度量面板：第一拍（fast 快照）之后的全量拍必须把失败维救活
 * （delivery 出数、主仓归档口径），time 与 health 两个视图的关闭数不再自相矛盾；
 * 节流语义下数字不漂、存量脏记录（updated_ts 缺失）不自锁。
 *
 * 断言面（锚定 /metrics 响应契约：kpis/reason/cache.status，不绑记录内部字段）：
 *  J0 夹具自检：冷跑落盘缓存（fixture 纪律=让实现自己写缓存，再篡改，不手写内部派生值）。
 *  J1 open 陈旧（条件B）+ delivery=null（条件A 但 TTL 内）→ 全量拍自愈：
 *     time 关闭数=2、与 health 关闭数一致（4vs5 收敛）、t-heal 不再报「不可算」、
 *     归档口径 reason=票号前缀+他账剔除（t260904-09 收窄契约，取代旧「多提交」措辞）。
 *  J2 TTL 内再查：响应剔除 generated_at/cache.computed_at 后逐字节稳定（数字不漂）。
 *  J3 条件A隔离（open 一致 + null + 过 TTL）→ 重探自愈。
 *  J4 updated_ts 缺失（NaN）→ 视为过期，不自锁。
 *  J5 SUYOU_METRICS_REPROBE_TTL_MIN=0 → 每请求必探仍自愈。
 *  J6 重开面板第一拍 fast：自愈后的快照关闭数即正确、status='stale'（cache-first 字面）。
 *
 * 与既有资产 intent 区别：t260903-09-kpi-invariants 守新鲜数据的人口自洽；
 * workbench/tests/delivery-recovery（developer L1）守记录内部的自愈机制与零 spawn 节流；
 * 本场景守「用户重开面板」两拍旅程与跨视图一致的响应契约面。
 *
 * 预期状态：实现段（t260904-04 第 2 步）已随本工作区落地——全绿；若回退实现则
 * J1~J6 红、J0 仍绿（夹具自检证明运行面健全，红=修复面真实存在）。Run: node integration/t260904-04/sc_metrics_stale_cache_heal_journey.mjs（cwd=仓库根）
 */
import { readFile, writeFile } from 'node:fs/promises'
import {
  NOW, DAY, iso, WORKFLOWS, ticketRow, withStub, callMetrics, findCacheFile, makeChecker,
} from '../t260903-09/lib_integration.mjs'

const { ok, done } = makeChecker()
// stubDeps git 桩的 deliveries 键 = args.join(' ')（不含 cwd，metrics.ts stubDeps 契约）。
// t260904-09 收窄后（契约增补段取代旧「多提交」措辞）：归档口径先取 `%H %s` 再按
// message 票号前缀过滤，逐前缀提交 `show --numstat` 求和——第二提交=引用性提及
// （票号不居首），被收窄剔除（fixture 同步钉住收窄行为：交付=50 非 80）。
const grepKey = (id) => `log --format=%H %s --grep ${id}`
const showKey = (hash) => `show --numstat --format= ${hash}`

/** 剔除易变字段后的稳定形态（与 golden 同纪律）。 */
function stripVolatile(body) {
  const b = JSON.parse(JSON.stringify(body))
  delete b.generated_at
  if (b.cache && typeof b.cache === 'object') delete b.cache.computed_at
  return JSON.stringify(b)
}

/** reason 串里取某票的段（'；' 分隔，段首=票 id）。 */
function reasonSegment(body, ticketId) {
  return String(body?.reason ?? '').split('；').find((s) => s.startsWith(`${ticketId}: `)) ?? ''
}

/** 毒化某票缓存记录（fixture 级篡改，不动实现）。 */
async function poison(cacheRoot, ticketId, { open, oldTs, dropTs }) {
  const p = await findCacheFile(cacheRoot, ticketId)
  if (p === null) throw new Error(`夹具失败：${ticketId} 缓存不存在（冷跑未落盘?）`)
  const rec = JSON.parse(await readFile(p, 'utf8'))
  rec.open = open
  rec.delivery = null
  rec.delivery_frozen = false
  if (dropTs) delete rec.updated_ts
  else rec.updated_ts = oldTs ? iso(NOW - 2 * 3600_000) : iso(NOW)
  await writeFile(p, JSON.stringify(rec, null, 1), 'utf8')
}

const stub = {
  project: 'demo',
  epics: [],
  workflows: WORKFLOWS,
  tickets: [
    ticketRow('t-heal', { createdAt: NOW - 3 * DAY, closedAt: NOW - DAY }),   // 被毒化对象（闭单票）
    ticketRow('t-ok', { createdAt: NOW - 2 * DAY, closedAt: NOW - DAY }),     // 健康闭单票
    ticketRow('t-live', { createdAt: NOW - DAY / 2 }),                        // 在制票（不可算属正常）
  ],
  deliveries: {
    // hash 必须满 40 位：实现按 `行.slice(41)` 取 subject 判票号前缀（%H 全 hash + 空格）
    [grepKey('t-heal')]: `${'a'.repeat(40)} t-heal squash 收口（一单一提交）\n${'b'.repeat(40)} 讨论档（引用 t-heal 教训）\n`,
    [showKey('a'.repeat(40))]: '50\t10\tf.ts\n',
    [grepKey('t-ok')]: `${'c'.repeat(40)} t-ok squash 收口（一单一提交）\n`,
    [showKey('c'.repeat(40))]: '5\t1\th.ts\n',
  },
}

const savedTtl = process.env.SUYOU_METRICS_REPROBE_TTL_MIN
try {
  await withStub(stub, async ({ deps, cacheRoot }) => {
    /* J0 夹具自检：冷跑全量，实现自己落盘缓存 */
    const cold = await callMetrics(deps, { view: 'time', window: 'all' })
    ok(cold.status === 200, 'J0 冷跑 200（夹具自检）')
    ok((await findCacheFile(cacheRoot, 't-heal')) !== null, 'J0 缓存已落盘（夹具自检）')

    /* J1 open 陈旧 + delivery=null：全量拍（重开面板第二拍）自愈 */
    await poison(cacheRoot, 't-heal', { open: true, oldTs: false, dropTs: false })
    const healed = await callMetrics(deps, { view: 'time', window: 'all' })
    const health = await callMetrics(deps, { view: 'health', window: 'all' })
    ok(healed.body?.kpis?.closed === 2, 'J1 time 关闭数自愈=2（陈旧 open 不再压计数）', `got ${JSON.stringify(healed.body?.kpis)}`)
    ok(health.body?.kpis?.closed === 2, 'J1 health 关闭数=2（直查口径）', `got ${JSON.stringify(health.body?.kpis)}`)
    ok(healed.body?.kpis?.closed === health.body?.kpis?.closed, 'J1 time/health 关闭数一致（4vs5 分叉收敛）')
    const dresp = await callMetrics(deps, { view: 'delivery', window: 'all' })
    const seg = reasonSegment(dresp.body, 't-heal')
    ok(seg !== '', 'J1 t-heal reason 段在场')
    ok(!seg.includes('不可算'), 'J1 交付维不再报不可算（失败维自愈）', seg)
    // t260904-09 收窄后新契约文案（契约增补段成文，取代旧「多提交」措辞）：
    // 票号前缀提交数 + 他账剔除计数；fixture 双提交一前缀一引用性提及，交付=50 证明他账未计入
    ok(seg.includes('归档口径') && seg.includes('前缀') && seg.includes('已剔'),
      'J1 归档口径 reason=票号前缀+他账剔除（t260904-09 收窄契约）', seg)
    ok(seg.includes('1 个'), 'J1 前缀提交恰 1（引用性提及他账被收窄剔除，交付=50 非 80）', seg)

    /* J2 TTL 内再查：响应逐字节稳定（数字不漂） */
    const again = await callMetrics(deps, { view: 'delivery', window: 'all' })
    ok(stripVolatile(again.body) === stripVolatile(dresp.body), 'J2 TTL 内命中：响应剔除易变字段后逐字节一致')

    /* J3 条件A隔离：open 一致 + delivery=null + updated_ts 过 TTL → 重探自愈 */
    await poison(cacheRoot, 't-heal', { open: false, oldTs: true, dropTs: false })
    const healed2 = await callMetrics(deps, { view: 'time', window: 'all' })
    ok(healed2.body?.kpis?.closed === 2, 'J3 过 TTL null 重探自愈（条件A，节流门放行过期记录）', `got ${JSON.stringify(healed2.body?.kpis)}`)

    /* J4 updated_ts 缺失（NaN）→ 不自锁 */
    await poison(cacheRoot, 't-heal', { open: false, oldTs: false, dropTs: true })
    const healed3 = await callMetrics(deps, { view: 'time', window: 'all' })
    ok(healed3.body?.kpis?.closed === 2, 'J4 updated_ts 缺失视为过期，存量脏记录不自锁', `got ${JSON.stringify(healed3.body?.kpis)}`)

    /* J5 TTL=0 → 每请求必探 */
    process.env.SUYOU_METRICS_REPROBE_TTL_MIN = '0'
    await poison(cacheRoot, 't-heal', { open: false, oldTs: false, dropTs: false })
    const healed4 = await callMetrics(deps, { view: 'time', window: 'all' })
    ok(healed4.body?.kpis?.closed === 2, 'J5 TTL=0 每请求必探仍自愈', `got ${JSON.stringify(healed4.body?.kpis)}`)
    delete process.env.SUYOU_METRICS_REPROBE_TTL_MIN

    /* J6 重开面板第一拍 fast：自愈后的快照即正确 */
    const fast = await callMetrics(deps, { view: 'time', window: 'all', mode: 'fast' })
    ok(fast.body?.cache?.status === 'stale', 'J6 fast 快照 status=stale（cache-first 契约字面）')
    ok(fast.body?.kpis?.closed === 2, 'J6 自愈后 fast 快照关闭数=2（第一拍即正确）', `got ${JSON.stringify(fast.body?.kpis)}`)
  })
} finally {
  if (savedTtl === undefined) delete process.env.SUYOU_METRICS_REPROBE_TTL_MIN
  else process.env.SUYOU_METRICS_REPROBE_TTL_MIN = savedTtl
}
process.exit(done('t260904-04-stale-cache-heal-journey'))
