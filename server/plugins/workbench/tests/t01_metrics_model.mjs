/**
 * integration/t260902-01/t01_metrics_model.mjs —— metrics M2a（t260902-01）面板纯逻辑单测。
 *
 * 直跑：node integration/t260902-01/t01_metrics_model.mjs（node ≥22.18 原生 type-stripping，
 * 直接 import .ts）。全桩化：localStorage 用内存桩，API 响应用固定 JSON 对象喂——
 * 不碰网络、不碰 3099、不依赖真外部源。覆盖方案步骤 4 的用例清单：
 * 面板状态持久化（含畸形 localStorage）、畸形 API 响应、饼形态组合（含不重复计数
 * 断言与模板缺失降级断言）、onPick 签名、KPI 格式化边界。
 */
import {
  loadPanelState, savePanelState, PANEL_STORAGE_KEY,
  isChartSpec, sanitizeMetricsResponse,
  buildTimeDonut, humanStageIds,
  formatMinutes, formatTokens, kpiCards, metricsQueryString,
} from './../src/client/metrics-model.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 内存 localStorage 桩（可预置毒化值）。 */
function memStorage(preset) {
  const m = new Map(preset ? Object.entries(preset) : [])
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    _map: m,
  }
}

/* ------------------------------------------------------------ A. 面板状态持久化 */

section('A. 面板状态：默认/持久化/畸形容错')
{
  const st = memStorage()
  const d = loadPanelState(st)
  ok(d.view === 'time' && d.window === '7d' && d.epic === 'all' && d.template === 'dev-lane' && d.shape === 'bar',
    '默认状态=time/7d/all/dev-lane/bar')
  savePanelState({ ...d, window: '30d', shape: 'donut' }, st)
  const r = loadPanelState(st)
  ok(r.window === '30d' && r.shape === 'donut', '往返读写一致')
  ok(String(st._map.get(PANEL_STORAGE_KEY)).includes('30d'), 'localStorage 落盘')
}
{
  // 畸形：坏 JSON / 非对象 / 非法枚举 / 字段类型错 / 超长串
  ok(loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: '{bad json' })).window === '7d', '坏 JSON → 默认')
  ok(loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: '"str"' })).view === 'time', '非对象 → 默认')
  const r = loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: JSON.stringify({ window: '1y', view: 'nope', epic: 'x'.repeat(100), shape: 'pie' }) }))
  ok(r.window === '7d' && r.view === 'time' && r.epic.length <= 41 && r.shape === 'bar',
    '非法枚举回默认 + epic 超长截断 + shape 非法回默认')
  ok(loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: 'x'.repeat(5000) })).window === '7d', '超长存值丢弃')
  // 局部坏字段保留其余
  const r2 = loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: JSON.stringify({ window: '30d', window2: 1, shape: 42 }) }))
  ok(r2.window === '30d' && r2.shape === 'bar', '局部坏字段只丢坏的')
  // 无 localStorage 环境：不抛
  ok(loadPanelState(undefined).view === 'time', '无存储环境读默认不抛')
  let threw = false
  try { savePanelState(loadPanelState(undefined), { setItem() { throw new Error('quota') } }) } catch { threw = true }
  ok(!threw, '写配额满不抛')
}

section('A2. t260904-04 KI-042：选择器退役——template/epic 持久化残留归一')
{
  // 旧版 localStorage 存过非 dev-lane 模板 / 非 all 立项 → 读时弃用，防锁死非 dev-lane 模板空面板
  const r = loadPanelState(memStorage({ [PANEL_STORAGE_KEY]: JSON.stringify({ template: 'chore-lane', epic: 'engine-hardening', project: 'suyou', window: '30d' }) }))
  ok(r.template === 'dev-lane', '非 dev-lane 模板残留归一 dev-lane')
  ok(r.epic === 'all', '立项残留归一 all')
  ok(r.project === 'suyou', 'project 残留保留（项目下拉启用）')
  ok(r.window === '30d', '其余字段不受归一影响')
  // 归一值写回覆盖残留（savePanelState 落归一状态）
  const st = memStorage({ [PANEL_STORAGE_KEY]: JSON.stringify({ template: 'chore-lane' }) })
  savePanelState(loadPanelState(st), st)
  ok(st._map.get(PANEL_STORAGE_KEY).includes('"dev-lane"') && !st._map.get(PANEL_STORAGE_KEY).includes('chore-lane'), '归一值写回覆盖残留')
}

/* ------------------------------------------------------------ B. ChartSpec / 响应解析 */

section('B. isChartSpec / sanitizeMetricsResponse 畸形输入')
{
  ok(!isChartSpec(null) && !isChartSpec('x') && !isChartSpec({}), '非对象判坏')
  ok(!isChartSpec({ kind: 'pie', title: 't', categories: [], series: [] }), '非法 kind 判坏')
  ok(!isChartSpec({ kind: 'bar', title: 't', categories: ['a'], series: [{ name: 's', data: [1, 2] }] }), '维度不齐判坏')
  ok(!isChartSpec({ kind: 'bar', title: 't', categories: ['a'], series: [{ name: 's', data: [NaN] }] }), 'NaN 判坏')
  ok(isChartSpec({ kind: 'donut', title: 't', categories: ['a'], series: [{ name: 's', data: [1] }], drill: true }), '合法 spec 通过')
}
{
  const r = sanitizeMetricsResponse({ error: 'window 非法', reason: 'window 非法' })
  ok(r.error === 'window 非法' && r.primary === null, '4xx {error} → error 承载人话')
  ok(sanitizeMetricsResponse(null).error !== null, '非对象 → error 不抛')
  ok(sanitizeMetricsResponse('str').error !== null, '字符串 → error 不抛')
  const good = sanitizeMetricsResponse({
    kpis: { tickets: 3, closed: 2, avg_delivery_min: 12.345, tokens_total: 1500 },
    charts: { primary: { kind: 'bar', title: 't', categories: ['plan', 'review'], series: [{ name: 's', data: [10, 20] }] }, secondaries: 'bad' },
    generated_at: '2026-09-02T00:00:00Z', cache: { status: 'hit' },
  })
  ok(good.error === null && good.primary?.kind === 'bar' && good.secondaries.length === 0, '坏 secondaries 丢弃不崩')
  ok(Math.round(good.kpis.avg_delivery_min * 100) === 1235, 'kpis 数值保留')
  const kbad = sanitizeMetricsResponse({ kpis: { tickets: 'x', closed: null }, charts: {} })
  ok(kbad.kpis.tickets === 0 && kbad.kpis.closed === 0, '坏 kpis 字段归零')
}

/* ------------------------------------------------------------ C. 饼形态组合 */

section('C. buildTimeDonut：机器扇区 + 人审合并单橙扇区（不重复计数）')
const primary = { kind: 'bar', title: 'stage 时长合计（分钟）', categories: ['create_plan', 'human_review', 'implement'], drill: true, series: [{ name: '时长(min)', data: [30, 15, 60] }] }
const fallback = { kind: 'donut', title: '时间去哪了：人审等待 vs 机器', categories: ['人审等待', '机器'], drill: true, series: [{ name: '占比', data: [15, 75] }] }
const stages = [
  { id: 'create_plan', exit: 'next' },
  { id: 'human_review', exit: 'human' },
  { id: 'implement', exit: 'next' },
]
{
  const d = buildTimeDonut(primary, fallback, stages)
  ok(d.degraded === false, '有模板 → 非降级')
  ok(d.slices.length === 3, '两机器扇区 + 一人审合并扇区')
  const human = d.slices.find(s => s.human)
  ok(!!human && human.name === '人审等待' && human.value === 15, '人审扇区=human stage 时长合并（15）')
  const total = d.slices.reduce((s, x) => s + x.value, 0)
  ok(total === 105, `全环合计=Σby_stage=105（不重复计数；实际 ${total}）`)
  ok(d.totalMin === 105 && Math.abs(d.humanRatio - 15 / 105) < 1e-9, '中心大字 N 与人等 X%')
  ok(!d.slices.filter(s => !s.human).some(s => s.name === 'human_review'), 'human stage 不进机器扇区')
}
{
  // 多个人审 stage 合并
  const p2 = { ...primary, categories: ['a', 'h1', 'h2', 'b'], series: [{ name: 's', data: [10, 5, 7, 8] }] }
  const s2 = [{ id: 'a' }, { id: 'h1', exit: 'human' }, { id: 'h2', exit: 'human' }, { id: 'b' }]
  const d = buildTimeDonut(p2, fallback, s2)
  const human = d.slices.find(x => x.human)
  ok(human.value === 12 && d.slices.length === 3, '多 human stage 合并为单一橙扇区')
}
{
  // 人审时长为 0：仍出独立橙扇区（红线「独立一块」），占比 0
  const p3 = { ...primary, categories: ['a', 'h'], series: [{ name: 's', data: [10, 0] }] }
  const d = buildTimeDonut(p3, fallback, [{ id: 'a' }, { id: 'h', exit: 'human' }])
  ok(d.slices.some(x => x.human && x.value === 0) && d.humanRatio === 0, '人审 0 分钟仍独立橙块')
}
{
  // 模板缺失 → 降级二分环（同橙色、degraded 显性标注）
  const d1 = buildTimeDonut(primary, fallback, null)
  ok(d1.degraded === true && d1.slices.length === 2, '模板 null → 降级二分环')
  ok(d1.slices.find(x => x.name === '人审等待')?.human === true, '降级环人审扇区恒橙标记')
  ok(d1.totalMin === 90 && Math.abs(d1.humanRatio - 15 / 90) < 1e-9, '降级环合计=人审+机器=90')
  const d2 = buildTimeDonut(primary, fallback, [])
  ok(d2.degraded === true, '空 stages 数组同降级')
  const d3 = buildTimeDonut(null, null, stages)
  ok(d3.slices.length === 0 && d3.totalMin === 0, 'primary 坏且无 fallback → 空饼不抛')
}
{
  ok(humanStageIds(null).size === 0 && humanStageIds('x').size === 0, 'humanStageIds 畸形容错')
  ok(humanStageIds([{ id: 'a', exit: 'human' }, { id: 'b' }]).has('a'), 'humanStageIds 判定')
}

/* ------------------------------------------------------------ D. KPI 格式化边界 */

section('D. KPI 卡与数字格式化边界')
{
  ok(formatMinutes(0) === '0' && formatMinutes(-5) === '0' && formatMinutes(NaN) === '0', '分钟 0/负/NaN')
  ok(formatMinutes(5.236) === '5.24', '分钟 <10 两位小数')
  ok(formatMinutes(42.36) === '42.4', '分钟 <100 一位小数')
  ok(formatMinutes(123.6) === '124', '分钟 >=100 取整')
  ok(formatMinutes(1e9) === '1,000,000,000', '超大分钟千分位')
  ok(formatTokens(0) === '0' && formatTokens(-1) === '0' && formatTokens(NaN) === '0', 'token 0/负/NaN')
  ok(formatTokens(9999) === '9,999' && formatTokens(15000) === '15k' && formatTokens(2_500_000) === '2.5M', 'token 分档')
  const cards = kpiCards({ tickets: 3, closed: 2, avg_delivery_min: 45.6, tokens_total: 12345 })
  ok(cards.length === 4 && cards[0].label === 'Tickets' && cards[2].value === '45.6 min', '四卡序与格式化')
  ok(kpiCards({ tickets: NaN, closed: NaN, avg_delivery_min: NaN, tokens_total: NaN })[3].value === '0', 'KPI NaN 全边界')
}

/* ------------------------------------------------------------ E. 查询串 + onPick 签名 */

section('E. metricsQueryString 与下钻签名')
{
  const q = metricsQueryString({ view: 'time', window: '30d', epic: 'none', project: '', template: 'dev-lane', shape: 'bar' })
  const p = new URLSearchParams(q)
  ok(p.get('window') === '30d' && p.get('epic') === 'none' && p.get('view') === 'time' && p.get('template') === 'dev-lane',
    '五参数（project 缺省不传）')
  ok(!q.includes('project='), '空 project 不进查询串')
  // onPick 签名（UI 层回调，本文件只断言 model 层的票 id 形状约束）：
  // 下钻数据面=副2 stackBar categories=票 id——isChartSpec 已保证 categories 为字符串数组。  ok(isChartSpec({ kind: 'stackBar', title: 't', categories: ['t260902-01'], series: [{ name: 's', data: [1] }] }), '票 id 作 categories 的 spec 合法（下钻数据面）')
}

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
