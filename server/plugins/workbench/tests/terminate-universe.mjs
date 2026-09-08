/**
 * terminate-universe.mjs —— t260903-09 S5：terminate/直并收口票的可见终态（audit 洞）。
 *
 * 根因：聚合宇宙=listTickets(project)，直并收口票已从工单列表消失 → 从度量宇宙
 * 整体消失。修复：宇宙=list ∪ 度量缓存存量（只读缓存文件，不 spawn 不回写），
 * reason 显式计数。
 *
 * W3 负向断言（可判定化）：ticket list API 响应集合不因本票扩大——stub 行对象
 * 逐字段快照比对 + 数组冻结，证明聚合侧宇宙补全绝不污染 list 语义。
 *
 * Run: node server/plugins/workbench/tests/terminate-universe.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, STAGES, ok, summary,
} from './lib.mjs'

const { buildMetricsResponse, defaultDeps, engineVersionOf, SOURCE_VERSION } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)
const { writeFile, mkdir } = await import('node:fs/promises')
const { join } = await import('node:path')

const savedStub = process.env.SUYOU_METRICS_STUB
const savedDir = process.env.SUYOU_METRICS_DIR

// 缓存目录布局（契约路径约定）：<SUYOU_METRICS_DIR>/<project>/data/metrics/
async function mkCacheDir(prefix) {
  // env 语义 = 根（SUYOU_METRICS_DIR），实现内部再拼 <project>/data/metrics/
  const root = freshDir(prefix)
  const dir = join(root, 'demo', 'data', 'metrics')
  const { mkdir } = await import('node:fs/promises')
  await mkdir(dir, { recursive: true })
  return { root, dir }
}
const engine = engineVersionOf(STAGES)

function archivedRec(id, opts = {}) {
  const t0 = opts.t0 ?? Date.parse('2026-08-29T01:00:00Z')
  const closedAt = opts.closedAt ?? Date.parse('2026-08-29T09:00:00Z')
  return {
    ticket_id: id, template: opts.template ?? 'dev-lane',
    durations: { by_stage: { plan: 3600e3, review: 3600e3 }, by_round: { plan: 3600e3, review: 3600e3 }, human_wait: 3600e3 },
    delivery: { base: 'main', add: 1200, del: 40, commits: 2 },
    tokens: { by_stage: {}, by_model: { 'deepseek/v3': 5000 }, in: 4000, out: 1000, cacheRead: 0 },
    open: opts.open ?? false, delivery_frozen: true,
    source_version: SOURCE_VERSION, engine_version: engine,
    updated_ts: new Date(NOW).toISOString(), computed_at: new Date(NOW).toISOString(),
    created_ms: t0, closed_ms: closedAt,
  }
}

{
  console.log('A. 宇宙补全：list 缺 t09-gone → 缓存存量计入 KPI/charts + reason 计数')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-term-cache-')
  await mkdir(cacheDir, { recursive: true })
  await writeFile(join(cacheDir, 't09-gone.json'), JSON.stringify(archivedRec('t09-gone')), 'utf8')
  await writeFile(join(cacheDir, 't09-broken.json'), '{not json', 'utf8') // 坏缓存：跳过不崩
  await writeFile(join(cacheDir, 't09-otherlane.json'), JSON.stringify(archivedRec('t09-otherlane', { template: 'other-lane' })), 'utf8') // 跨模板：不混排
  await writeFile(join(cacheDir, 't09-oldv.json'), JSON.stringify({ ...archivedRec('t09-oldv'), source_version: 'v0' }), 'utf8') // schema 失配：不并入
  const live = closedTicket('t09-live', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })

  // W3 负向断言：行对象冻结 + 快照——宇宙补全不得触碰 list 语义
  const frozenRows = Object.freeze([Object.freeze({ ...live })])
  const snapshot = JSON.stringify(frozenRows)
  const stub = baseStub({ tickets: frozenRows })
  process.env.SUYOU_METRICS_DIR = cacheRoot
  process.env.SUYOU_METRICS_STUB = writeStub(freshDir('t09-term-stub-'), stub)
  const deps = defaultDeps('/stub-repo', () => NOW)

  const r = await buildMetricsResponse({ view: 'delivery', window: '7d' }, deps)
  ok('200', r.status === 200, JSON.stringify(r.body).slice(0, 300))
  ok('archived 票计入 KPI（tickets=2=live1+gone1）', r.body.kpis.tickets === 2, JSON.stringify(r.body.kpis))
  ok('archived 票 delivery 计入（add=1200+live0？）→ 有变更票=2', r.body.kpis.tickets === 2)
  const donut = r.body.charts.secondaries.find((c) => c.kind === 'donut')
  // t260904-09 四桶：有变更 1（archived）+ 不可算（数据缺失）1（live 无 delivery），
  // 零变更/在制两桶为 0——互斥不混装
  ok('占比 donut 四桶：有变更 1 + 不可算 1（零变更/在制=0）', donut && donut.series[0].data[0] === 1 && donut.series[0].data[3] === 1 && donut.series[0].data[1] === 0 && donut.series[0].data[2] === 0, JSON.stringify(donut?.series))
  ok('reason 计数=1（坏 JSON/跨模板/失配三票不混入）', String(r.body.reason ?? '').includes('度量宇宙补全：1 票'), String(r.body.reason ?? '').slice(0, 240))
  ok('W3：list 行集合不变（冻结数组+快照一致）', JSON.stringify(frozenRows) === snapshot && frozenRows.length === 1)

  console.log('A2. archived 票 open 语义取缓存 rec.open（closed）→ closed 计数')
  const r2 = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
  ok('archived closed 票计入 closed（closed=2）', r2.body.kpis.closed === 2, JSON.stringify(r2.body.kpis))
}

{
  console.log('B. 冷项目（无缓存目录）：宇宙补全空转不崩')
  process.env.SUYOU_METRICS_DIR = freshDir('t09-term-cold-')
  process.env.SUYOU_METRICS_STUB = writeStub(freshDir('t09-term-stub2-'), baseStub({ tickets: [] }))
  const deps = defaultDeps('/stub-repo', () => NOW)
  const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
  ok('200 空态', r.status === 200 && r.body.kpis.tickets === 0)
  ok('无 reason 混入', r.body.reason === undefined)
}

process.env.SUYOU_METRICS_STUB = savedStub
process.env.SUYOU_METRICS_DIR = savedDir
process.exit(summary('terminate-universe') ? 0 : 1)
