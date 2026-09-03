/**
 * metrics-fast-path.mjs —— t260903-09 S3：cache-first 加载（先吐缓存后台刷新）。
 *
 * 钉死：
 *  A 热缓存：full 模式零 showTicket spawn（锚点已入缓存，不再逐票 show 补锚点）
 *     ——「提速验收只认热缓存零 spawn」；
 *  B fast 模式：只读缓存聚合，零 spawn、cache.status='stale'、缺票 reason 显式
 *     （快照宁可缺票不可错数）；
 *  C 旧版缓存记录（无锚点槽位）full 模式回落 list 行 timeline/show 补齐（向后兼容）；
 *  D mode 非法值 4xx 防穿；重复参数 4xx（同名重复不容错）。
 *
 * Run: node server/dsh/workbench/tests/metrics-fast-path.mjs  (cwd = repo root)
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

function recFor(id, t0, closedAt, extra = {}) {
  return {
    ticket_id: id, template: 'dev-lane',
    durations: { by_stage: { plan: 3600e3 }, by_round: { plan: 3600e3 }, human_wait: 0 },
    delivery: null, tokens: null, open: closedAt === null,
    delivery_frozen: false,
    source_version: SOURCE_VERSION, engine_version: engine,
    updated_ts: new Date(NOW).toISOString(), computed_at: new Date(NOW).toISOString(),
    created_ms: t0, closed_ms: closedAt,
    ...extra,
  }
}

const mkDeps = (stub, cacheRoot) => {
  // env 先行：defaultDeps 在调用时读缝（SUYOU_METRICS_STUB），晚设就走真通路
  process.env.SUYOU_METRICS_STUB = writeStub(freshDir('t09-fast-stub-'), stub)
  process.env.SUYOU_METRICS_DIR = cacheRoot
  const deps = defaultDeps('/stub-repo', () => NOW)
  let spawnCount = 0
  const rawShow = deps.showTicket.bind(deps)
  deps.showTicket = async (id) => { spawnCount += 1; return rawShow(id) }
  deps.showTicketCount = () => spawnCount
  return { deps, stubPath: process.env.SUYOU_METRICS_STUB, cacheRoot }
}

const withEnv = async (cacheRoot, stubPath, fn) => {
  process.env.SUYOU_METRICS_DIR = cacheRoot
  process.env.SUYOU_METRICS_STUB = stubPath
  try { return await fn() } finally {
    delete process.env.SUYOU_METRICS_STUB
    delete process.env.SUYOU_METRICS_DIR
  }
}

{
  console.log('A+B. 热缓存：full 零 spawn、fast 零 spawn+stale、缺票显式')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-fast-cache-')
  await mkdir(cacheDir, { recursive: true })
  const t1 = closedTicket('t09-f1', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const t2 = closedTicket('t09-f2', baseStub(), { t0: Date.parse('2026-08-30T02:00:00Z'), closedAt: Date.parse('2026-08-30T05:00:00Z') })
  await writeFile(join(cacheDir, 't09-f1.json'), JSON.stringify(recFor('t09-f1', Date.parse('2026-08-30T01:00:00Z'), Date.parse('2026-08-30T04:00:00Z'))), 'utf8')
  await writeFile(join(cacheDir, 't09-f2.json'), JSON.stringify(recFor('t09-f2', Date.parse('2026-08-30T02:00:00Z'), Date.parse('2026-08-30T05:00:00Z'))), 'utf8')
  const { deps, stubPath } = mkDeps(baseStub({ tickets: [t1, t2] }), cacheRoot)
  await withEnv(cacheRoot, stubPath, async () => {
    const rf = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps)
    ok('fast 200', rf.status === 200, JSON.stringify(rf.body).slice(0, 200))
    ok('fast cache.status=stale（契约 bump 新字面）', rf.body.cache?.status === 'stale')
    ok('fast 零 showTicket spawn', deps.showTicketCount() === 0, String(deps.showTicketCount()))
    ok('fast KPI 来自缓存锚点（tickets=2 closed=2）', rf.body.kpis.tickets === 2 && rf.body.kpis.closed === 2, JSON.stringify(rf.body.kpis))

    const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
    ok('full 热缓存 cache.status=hit', r.body.cache?.status === 'hit')
    ok('full 热缓存零 showTicket spawn（提速验收口径）', deps.showTicketCount() === 0, String(deps.showTicketCount()))

    // 缺票显式：缓存里只有 f1/f2，列表多一张 f3 → fast 跳过并 reason
    const t3 = closedTicket('t09-f3', baseStub(), { t0: Date.parse('2026-08-30T03:00:00Z'), closedAt: Date.parse('2026-08-30T06:00:00Z') })
    const { deps: deps3, stubPath: stub3 } = mkDeps(baseStub({ tickets: [t1, t2, t3] }), cacheRoot)
    const rf3 = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps3)
    ok('fast 缺票不现算（tickets=2≠3）', rf3.body.kpis.tickets === 2, JSON.stringify(rf3.body.kpis))
    ok('fast 缺票 reason 显式', String(rf3.body.reason ?? '').includes('t09-f3') && String(rf3.body.reason).includes('fast'), String(rf3.body.reason ?? '').slice(0, 200))
    ok('fast 缺票零 spawn', deps3.showTicketCount() === 0)
    deps.showTicketCount = deps3.showTicketCount // noop 防误用
  })
}

{
  console.log('C. 旧版缓存记录（无锚点）→ full 回落 list 行 timeline 补齐 + 迁移回写（F2）')
  const { root: cacheRoot, dir: cacheDir } = await mkCacheDir('t09-fast-old-')
  await mkdir(cacheDir, { recursive: true })
  const legacy = recFor('t09-old', Date.parse('2026-08-30T01:00:00Z'), Date.parse('2026-08-30T04:00:00Z'))
  delete legacy.created_ms
  delete legacy.closed_ms
  await writeFile(join(cacheDir, 't09-old.json'), JSON.stringify(legacy), 'utf8')
  const t = closedTicket('t09-old', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const { deps, stubPath } = mkDeps(baseStub({ tickets: [t] }), cacheRoot)
  await withEnv(cacheRoot, stubPath, async () => {
    const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
    ok('旧版记录 full 200（list 行 timeline 免 spawn）', r.status === 200 && deps.showTicketCount() === 0, `spawn=${deps.showTicketCount()}`)
    ok('旧版记录 KPI 正常（锚点由行内 timeline 补）', r.body.kpis.tickets === 1 && r.body.kpis.closed === 1)
    // F2 迁移回写：旧版记录命中后按行内 timeline 补**真实**锚点并落盘升级——
    // 存量数据由此收敛为带锚点新版，fast 对真机存量不再永久跳过。
    const { readFile } = await import('node:fs/promises')
    const after = JSON.parse(await readFile(join(cacheDir, 't09-old.json'), 'utf8'))
    ok('旧版记录已迁移回写锚点（created_ms/closed_ms 落盘）',
      after.created_ms === Date.parse('2026-08-30T01:00:00Z') && after.closed_ms === Date.parse('2026-08-30T04:00:00Z'),
      JSON.stringify({ created_ms: after.created_ms, closed_ms: after.closed_ms }))
    // 迁移后 fast 直接受益：不再「fast 无可用缓存」跳过（F2 验收场景）
    const f = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps)
    ok('迁移后 fast 计入该票（存量不再永久跳过）', f.body.kpis.tickets === 1 && f.body.kpis.closed === 1, JSON.stringify(f.body.kpis))
    ok('迁移后 fast 无跳过 reason', !String(f.body.reason ?? '').includes('fast 无可用缓存'), String(f.body.reason ?? '').slice(0, 120))
  })
}

// F3 近似归窗：列表外旧版记录（无 timeline 可补）按 computed_at 近似计入 full，
// reason 显式声明近似且 notice 排首；近似锚点绝不回写缓存（防近似值永久化）。
{
  console.log('C2. 存量旧版记录近似归窗（列表外，无 timeline）')
  const { root: cacheRoot2, dir: cacheDir2 } = await mkCacheDir('t09-fast-approx-')
  await mkdir(cacheDir2, { recursive: true })
  const legacy2 = recFor('t09-gone', Date.parse('2026-08-30T01:00:00Z'), Date.parse('2026-08-30T04:00:00Z'))
  delete legacy2.created_ms
  delete legacy2.closed_ms
  legacy2.computed_at = '2026-08-31T12:00:00Z' // 测试 NOW=2026-09-01T00:30Z，近似锚点须在窗内
  await writeFile(join(cacheDir2, 't09-gone.json'), JSON.stringify(legacy2), 'utf8')
  const { deps: deps2, stubPath: stubPath2 } = mkDeps(baseStub({ tickets: [] }), cacheRoot2) // 列表为空=列表外存量
  await withEnv(cacheRoot2, stubPath2, async () => {
    const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps2)
    ok('存量旧版记录近似归窗计入 tickets=1', r.body.kpis.tickets === 1, JSON.stringify(r.body.kpis))
    ok('reason 含宇宙补全 notice 且排首', String(r.body.reason ?? '').startsWith('度量宇宙补全'), String(r.body.reason ?? '').slice(0, 160))
    ok('reason 声明近似归窗', String(r.body.reason ?? '').includes('近似归窗'), String(r.body.reason ?? '').slice(0, 160))
    const { readFile } = await import('node:fs/promises')
    const after = JSON.parse(await readFile(join(cacheDir2, 't09-gone.json'), 'utf8'))
    ok('近似锚点不回写缓存（防近似值永久化）', after.created_ms === undefined && after.closed_ms === undefined, JSON.stringify(after.created_ms))
    // fast 门同享近似回落：存量旧版记录不再让 fast 全零（F2 验收复测口径）
    const f = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps2)
    ok('fast 对存量旧版记录按近似归窗计入（不再全零快照）', f.body.kpis.tickets === 1, JSON.stringify(f.body.kpis))
  })
}

{
  console.log('D. mode 防穿：非法值/重复参数 4xx')
  const { deps, stubPath } = mkDeps(baseStub({ tickets: [] }), freshDir('t09-fast-e-'))
  await withEnv((await mkCacheDir('t09-fast-e2-')).root, stubPath, async () => {
    const r1 = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'hack' }, deps)
    ok('mode 非法 → 400+人话', r1.status === 400 && String(r1.body.error).includes('mode'), JSON.stringify(r1.body))
    const r2 = await buildMetricsResponse({ view: 'time', window: '7d', mode: ['fast', 'full'] }, deps)
    ok('mode 重复 → 400（无取首个容错）', r2.status === 400, JSON.stringify(r2.body))
    const r3 = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps)
    ok('冷缓存 fast：200+stale 空态不炸', r3.status === 200 && r3.body.cache?.status === 'stale' && r3.body.kpis.tickets === 0)
  })
}

process.env.SUYOU_METRICS_STUB = savedStub
process.env.SUYOU_METRICS_DIR = savedDir
process.exit(summary('metrics-fast-path') ? 0 : 1)
