/**
 * t260904_09_settle_snapshot.mjs —— settle 出仓快照读侧收口（KI-017 引擎侧欠账）。
 *
 * 覆盖：
 *  ① readSettleSnapshot：正常快照读取 / 畸形 JSON / 缺字段 / 无文件 降级；
 *  ② ticketRecord 优先级：settle 快照 > 现算 > 归档 grep——快照命中时 delivery/
 *     tokens=快照值、delivery_frozen=true、reason 标 settle 快照；zero_change
 *     快照 reason 显式「非本票交付」；
 *  ③ SOURCE_VERSION bump：旧版本缓存记录整条作废重算（归档收窄入口）；
 *  ④ 归档口径收窄锚：只计票号前缀 squash 提交（05 复刻：grep 5 条/前缀 1 条
 *     =5658 而非 5783）；
 *  ⑤ donut 四桶拆分：有变更 / 已收口·零变更 / 未交付（在制）/ 不可算（数据缺失），
 *     互斥且 Σ=票数。
 *
 * Run: node server/dsh/workbench/tests/t260904_09_settle_snapshot.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, STAGES,
} from './lib.mjs'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'

const {
  buildMetricsResponse, defaultDeps, engineVersionOf,
  readSettleSnapshot, resolveMetricsCacheDir, SOURCE_VERSION,
} = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)

const H = (n) => String(n).repeat(39) + String(n)

let PASS = 0, FAIL = 0
function ok2(cond, label, detail = '') {
  if (cond) { PASS++; console.log('  ok  ' + label) } else { FAIL++; console.log('  FAIL ' + label + (detail ? ' | ' + String(detail).slice(0, 300) : '')) }
}
// lib.mjs 无 openTicket 导出——open 行就地构造（status='open' + 开放 timeline）
function openTicket(id, stub, opts = {}) {
  const t0 = opts.t0 ?? Date.parse('2026-08-29T01:00:00Z')
  return {
    id, project: stub.project, epic: opts.epic ?? 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'running', status: 'open', role: 'developer',
    updated: new Date(t0 + 2 * 3600e3).toISOString(), worktree: `.worktrees/${id}`,
    timeline: [
      { at: new Date(t0).toISOString(), stage: 'plan', state: 'closed' },
      { at: new Date(t0 + 3600e3).toISOString(), stage: 'review', state: 'running' },
      { at: new Date(t0 + 2 * 3600e3).toISOString(), stage: 'implement', state: 'running' },
    ],
    ...opts.extra,
  }
}

const saved = {}
for (const k of ['SUYOU_METRICS_DIR', 'SUYOU_METRICS_STUB', 'SUYOU_USAGE_LEDGER_DIR']) { saved[k] = process.env[k]; delete process.env[k] }
const restore = () => { for (const k of Object.keys(saved)) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k] } }

// ---- ① readSettleSnapshot 三态
{
  console.log('① readSettleSnapshot：正常 / 畸形 / 无文件')
  const root = freshDir('t09-snap-')
  const dir = join(root, 'demo', 'data', 'settle')
  await mkdir(dir, { recursive: true })
  const good = {
    schema_version: 'v1', ticket_id: 't09-s1', project_key: 'demo',
    squash_commit: 'abc1234', settled_at: '2026-09-04T00:00:00Z',
    tokens: { in: 100, out: 20, cacheRead: 5, by_stage: {}, by_model: { 'p/m': 120 }, by_stage_available: false, tokens_zero: false },
    delivery: { base: 'deadbeef', add: 10, del: 2, commits: 1, squash_commit: 'abc1234', zero_change: false },
  }
  await writeFile(join(dir, 't09-s1.json'), JSON.stringify(good))
  const r1 = await readSettleSnapshot(dir, 't09-s1')
  ok2(r1.snap && r1.snap.tokens.in === 100 && r1.snap.delivery.add === 10, '正常快照读出 tokens+delivery', JSON.stringify(r1))
  ok2(r1.snap.delivery.squash_commit === 'abc1234', 'squash_commit 注记透传')
  await writeFile(join(dir, 't09-s2.json'), '{broken')
  const r2 = await readSettleSnapshot(dir, 't09-s2')
  ok2(!r2.snap && String(r2.reason).includes('不可解析'), '畸形 JSON → null+reason', String(r2.reason))
  await writeFile(join(dir, 't09-s3.json'), JSON.stringify({ delivery: { add: 'x' }, tokens: {} }))
  const r3 = await readSettleSnapshot(dir, 't09-s3')
  ok2(!r3.snap && String(r3.reason).includes('字段缺失'), '缺字段/非法数值 → null', String(r3.reason))
  const r4 = await readSettleSnapshot(dir, 't09-absent')
  ok2(!r4.snap && String(r4.reason).includes('无 settle 快照'), '无文件 → null+人话 reason')
  // resolveSettleDir 与缓存同根链
  process.env.SUYOU_METRICS_DIR = root
  ok2(resolveMetricsCacheDir('demo').settleDir === join(root, 'demo', 'data', 'settle'), 'settleDir 与缓存同根链', resolveMetricsCacheDir('demo').settleDir)
  // integration R6 回归：SETTLE env 在链头（替换项目根整体），写读同序不分叉
  const alt = freshDir('t09-snap-alt-')
  process.env.SANDBAR_SETTLE_SNAPSHOT_DIR = alt
  ok2(resolveMetricsCacheDir('demo').settleDir === join(alt, 'demo', 'data', 'settle'), 'SETTLE env 链头生效（写读同根）', resolveMetricsCacheDir('demo').settleDir)
  ok2(resolveMetricsCacheDir('demo').dir === join(root, 'demo', 'data', 'metrics'), 'SETTLE env 不影响缓存目录', resolveMetricsCacheDir('demo').dir)
  const rAlt = await readSettleSnapshot(resolveMetricsCacheDir('demo').settleDir, 't09-s1')
  ok2(!rAlt.snap, '替代根下无快照 → 不可见（写读同链的证据面）')
  await mkdir(join(alt, 'demo', 'data', 'settle'), { recursive: true })
  await writeFile(join(alt, 'demo', 'data', 'settle', 't09-s1.json'), JSON.stringify(good))
  const rAlt2 = await readSettleSnapshot(resolveMetricsCacheDir('demo').settleDir, 't09-s1')
  ok2(rAlt2.snap && rAlt2.snap.tokens.in === 100, '替代根下有快照 → 读出（R6 修复面）')
  delete process.env.SANDBAR_SETTLE_SNAPSHOT_DIR
  delete process.env.SUYOU_METRICS_DIR
}

// ---- ②③ ticketRecord 快照优先级 + zero_change reason
async function runScenario({ ticket, cacheRec, snapshot }) {
  const root = freshDir('t09-pri-')
  const stubDir = freshDir('t09-pri-stub-')
  const cacheDir = join(root, 'demo', 'data', 'metrics')
  const settleDir = join(root, 'demo', 'data', 'settle')
  await mkdir(cacheDir, { recursive: true })
  if (cacheRec) await writeFile(join(cacheDir, ticket.id + '.json'), JSON.stringify(cacheRec))
  if (snapshot) {
    await mkdir(settleDir, { recursive: true })
    await writeFile(join(settleDir, ticket.id + '.json'), JSON.stringify(snapshot))
  }
  process.env.SUYOU_METRICS_DIR = root
  process.env.SUYOU_METRICS_STUB = writeStub(stubDir, baseStub({ tickets: [ticket] }))
  const deps = defaultDeps('/stub-repo', () => NOW)
  const r = await buildMetricsResponse({ view: 'time', window: 'all' }, deps)
  const rec = JSON.parse(await readFile(join(cacheDir, ticket.id + '.json'), 'utf8'))
  return { r, rec }
}

{
  console.log('② 快照优先级：delivery/tokens=快照值、frozen=true、reason 标快照')
  const t = closedTicket('t09-p1', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const snap = {
    schema_version: 'v1', ticket_id: 't09-p1', project_key: 'demo', squash_commit: 'feed123',
    settled_at: '2026-09-04T00:00:00Z',
    tokens: { in: 7, out: 8, cacheRead: 9, by_stage: {}, by_model: {}, by_stage_available: false, tokens_zero: false },
    delivery: { base: 'aa', add: 2632, del: 3026, commits: 1, squash_commit: 'feed123', zero_change: false },
  }
  const { r, rec } = await runScenario({ ticket: t, snapshot: snap })
  ok2(r.status === 200, '200', JSON.stringify(r.body).slice(0, 200))
  ok2(rec.delivery.add === 2632 && rec.delivery.commits === 1, 'delivery=快照值（非归档 grep）', JSON.stringify(rec.delivery))
  ok2(rec.delivery.squash_commit === 'feed123', 'squash_commit 注记入缓存记录')
  ok2(rec.tokens.in === 7, 'token=快照值', JSON.stringify(rec.tokens))
  ok2(rec.delivery_frozen === true, 'delivery_frozen=true')
  ok2(String(r.body.reason).includes('settle 快照') && String(r.body.reason).includes('feed123'), 'reason 标 settle 快照+真身 hash', String(r.body.reason).slice(0, 200))
}
{
  console.log('②b zero_change 快照：reason 显式「非本票交付」')
  const t = closedTicket('t09-p2', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const snap = {
    schema_version: 'v1', ticket_id: 't09-p2', project_key: 'demo', squash_commit: 'badc567',
    settled_at: '2026-09-04T00:00:00Z',
    tokens: { in: 1, out: 1, cacheRead: 0, by_stage: {}, by_model: {}, by_stage_available: false, tokens_zero: true },
    delivery: { base: 'bb', add: 0, del: 0, commits: 0, squash_commit: 'badc567', zero_change: true },
  }
  const { r } = await runScenario({ ticket: t, snapshot: snap })
  ok2(String(r.body.reason).includes('收口零变更') && String(r.body.reason).includes('非本票交付'), 'zero_change reason 语义', String(r.body.reason).slice(0, 200))
}
{
  console.log('③ SOURCE_VERSION bump：旧版缓存整条作废重算（v1 记录被 v2 门挡下）')
  const root = freshDir('t09-bump-')
  const stubDir = freshDir('t09-bump-stub-')
  const cacheDir = join(root, 'demo', 'data', 'metrics')
  await mkdir(cacheDir, { recursive: true })
  const stale = {
    ticket_id: 't09-p3', template: 'dev-lane',
    durations: { by_stage: {}, by_round: {}, human_wait: 0 },
    delivery: { base: 'x', add: 5783, del: 0, commits: 5 }, // 旧口径 5783（若命中不重算即露出）
    tokens: null, open: false, delivery_frozen: true,
    source_version: 'v1', engine_version: engineVersionOf(STAGES),
    updated_ts: new Date(NOW).toISOString(), computed_at: new Date(NOW).toISOString(),
  }
  await writeFile(join(cacheDir, 't09-p3.json'), JSON.stringify(stale))
  process.env.SUYOU_METRICS_DIR = root
  process.env.SUYOU_METRICS_STUB = writeStub(stubDir, baseStub({
    tickets: [closedTicket('t09-p3', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })],
  }))
  const deps = defaultDeps('/stub-repo', () => NOW)
  const r = await buildMetricsResponse({ view: 'time', window: 'all' }, deps)
  const rec = JSON.parse(await readFile(join(cacheDir, 't09-p3.json'), 'utf8'))
  ok2(r.status === 200 && rec.source_version === SOURCE_VERSION && SOURCE_VERSION === 'v2', 'v1 记录作废、按 v2 重算落盘', rec.source_version)
  ok2(rec.delivery === null || rec.delivery.add !== 5783, '旧口径 5783 未存活（确实重算了）', JSON.stringify(rec.delivery))
}

// ---- ④ 归档口径收窄锚（05 复刻）
{
  console.log('④ 归档收窄：grep 5 条 / 前缀 1 条 → 5658 而非 5783（05 复刻）')
  const H1 = H('a'), H2 = H('b'), H3 = H('c'), H4 = H('d'), H5 = H('e')
  const deps = {
    repo: '/stub-repo',
    git: async (cwd, args) => {
      const key = `${cwd}::${args.join(' ')}`
      const table = {
        '/stub-repo::log --format=%H %s --grep t260904-05': [
          `${H2} 编号修正（提及 t260904-05）`,
          `${H3} t260904-05 squash 收口（一单一提交，KI-006）`,
          `${H1} 立项收尾 t260904-05`,
          `${H4} 讨论档归档 t260904-05`,
          `${H5} KI 登记 t260904-05`,
        ].join('\n'),
        [`/stub-repo::show --numstat --format= ${H3}`]: '2632\t3026\ta.ts',
        [`/stub-repo::show --numstat --format= ${H1}`]: '33\t0\tb.md',
        [`/stub-repo::show --numstat --format= ${H2}`]: '8\t0\tc.md',
        [`/stub-repo::show --numstat --format= ${H4}`]: '83\t0\td.md',
        [`/stub-repo::show --numstat --format= ${H5}`]: '1\t0\te.md',
      }
      if (!(key in table)) throw new Error('stub 未备: ' + key)
      return table[key]
    },
    now: () => NOW,
  }
  const { computeDelivery } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)
  const d = await computeDelivery(deps, { id: 't260904-05' })
  ok2(d.delivery && d.delivery.add + d.delivery.del === 5658, '前缀收窄后合计=5658（非 5783）', JSON.stringify(d))
  ok2(d.delivery.commits === 1, '只计 1 个前缀提交', JSON.stringify(d.delivery))
  ok2(d.frozen === true && String(d.reason).includes('已剔他账'), 'frozen + reason 点名剔除', String(d.reason))
}

// ---- ⑤ donut 四桶
{
  console.log('⑤ donut 四桶：互斥且 Σ=票数')
  const root = freshDir('t09-donut-')
  const stubDir = freshDir('t09-donut-stub-')
  const cacheDir = join(root, 'demo', 'data', 'metrics')
  await mkdir(cacheDir, { recursive: true })
  const mk = (id, delivery, open, frozen = true) => ({
    ticket_id: id, template: 'dev-lane',
    durations: { by_stage: {}, by_round: {}, human_wait: 0 },
    delivery, tokens: null, open, delivery_frozen: frozen,
    source_version: SOURCE_VERSION, engine_version: engineVersionOf(STAGES),
    updated_ts: new Date(NOW).toISOString(), computed_at: new Date(NOW).toISOString(),
    created_ms: Date.parse('2026-08-30T01:00:00Z'), closed_ms: open ? null : Date.parse('2026-08-30T04:00:00Z'),
  })
  const recs = [
    mk('t09-d1', { base: 'x', add: 10, del: 0, commits: 1 }, false),                       // 有变更
    mk('t09-d2', { base: 'x', add: 0, del: 0, commits: 0, squash_commit: 'h1', zero_change: true }, false), // 已收口·零变更
    mk('t09-d3', null, true),                                                              // 未交付（在制）
    mk('t09-d4', null, false),                                                             // 不可算
  ]
  for (const r of recs) await writeFile(join(cacheDir, r.ticket_id + '.json'), JSON.stringify(r))
  process.env.SUYOU_METRICS_DIR = root
  process.env.SUYOU_METRICS_STUB = writeStub(stubDir, baseStub({ tickets: [
    closedTicket('t09-d1', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') }),
    closedTicket('t09-d2', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') }),
    openTicket('t09-d3', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z') }),
    closedTicket('t09-d4', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') }),
  ] }))
  const deps = defaultDeps('/stub-repo', () => NOW)
  const r = await buildMetricsResponse({ view: 'delivery', window: 'all' }, deps)
  const charts = r.body.charts ?? {}
  const all = [charts.primary, ...(charts.secondaries ?? [])].filter(Boolean)
  const chart = all.find((c) => String(c?.title ?? '').includes('有无代码变更票占比'))
  ok2(Boolean(chart), 'donut chart 在场', JSON.stringify(charts).slice(0, 300))
  if (chart) {
    const data = chart.series[0].data
    ok2(data[0] === 1 && data[1] === 1 && data[2] === 1 && data[3] === 1, '四桶各 1（互斥）', JSON.stringify(data))
    ok2(data.reduce((a, b) => a + b, 0) === recs.length, 'Σ=票数', JSON.stringify(data))
    ok2(chart.categories.includes('已收口·零变更') && chart.categories.includes('不可算（数据缺失）'), '桶文案语义拆开')
  }
}

restore()
console.log('SUMMARY pass=%d fail=%d', PASS, FAIL)
process.exit(FAIL > 0 ? 1 : 0)
