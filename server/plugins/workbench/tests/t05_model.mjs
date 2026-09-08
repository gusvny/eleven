#!/usr/bin/env node
/**
 * t05_model.mjs —— t260902-05 模型层单测（node 直跑，type-stripping）。
 *
 * 覆盖（方案 R3 ③）：
 *   A. 时间窗 1d/3d：PANEL_WINDOWS 枚举 + loadPanelState 容错（1d/3d 合法、
 *      越界值回默认、坏 JSON/超长/局部坏字段不炸）。
 *   B. 空态判定（t260902-05⑥）：specIsBlank/donutIsBlank 全零/缺 series/畸形 data。
 *   C. sanitizeMetricsResponse：reason 字段承载与截断、畸形响应容错。
 */
import {
  PANEL_WINDOWS, donutIsBlank, loadPanelState, sanitizeMetricsResponse, specIsBlank,
} from './../src/client/metrics-model.ts'

let passed = 0
let failed = 0
function ok(cond, label) { if (cond) { passed++; console.log(`  ok ${label}`) } else { failed++; console.log(`  FAIL ${label}`) } }
function section(t) { console.log(`\n== ${t}`) }

/* A. 时间窗 */
section('A 时间窗 1d/3d')
ok(PANEL_WINDOWS.join(',') === '1d,3d,7d,30d,all', `PANEL_WINDOWS 枚举（实得 ${PANEL_WINDOWS.join(',')}）`)
{
  const s = loadPanelState({ getItem: () => JSON.stringify({ view: 'time', window: '3d', epic: 'all', project: '', template: 'dev-lane', shape: 'bar' }), setItem: () => {} })
  ok(s.window === '3d', '持久化 window=3d 合法读回')
  const s2 = loadPanelState({ getItem: () => JSON.stringify({ window: '2d' }), setItem: () => {} })
  ok(s2.window === '7d', '非法 window=2d 回默认 7d')
  const s3 = loadPanelState({ getItem: () => '{bad json', setItem: () => {} })
  ok(s3.window === '7d' && s3.view === 'time', '坏 JSON 不炸回默认')
  const s4 = loadPanelState({ getItem: () => JSON.stringify({ window: '1d', epic: 'x'.repeat(99) }), setItem: () => {} })
  ok(s4.window === '1d' && s4.epic.length <= 41, '1d 读回 + 超长 epic 截断（局部坏字段不毁整体）')
}

/* B. 空态判定 */
section('B 空态判定 specIsBlank/donutIsBlank')
ok(specIsBlank(null) === true, 'spec null → 空态')
ok(specIsBlank({ kind: 'donut', title: '', categories: [], series: [], drill: true }) === true, 'categories 空 → 空态')
ok(specIsBlank({ kind: 'donut', title: '', categories: ['人审等待', '机器'], series: [{ name: '占比', data: [0, 0] }], drill: true }) === true,
  '全零 donut → 空态（用户投诉「时间去哪了」白块根因面）')
ok(specIsBlank({ kind: 'donut', title: '', categories: ['人审等待', '机器'], series: [{ name: '占比', data: [0, 5] }, { name: 'x', data: [0, NaN] }], drill: true }) === false,
  '任一非零 → 可绘（NaN 按 0 计不救场）')
ok(specIsBlank({ kind: 'bar', title: '', categories: ['a'], series: [{ name: 'x', data: ['bad'] }], drill: true }) === true,
  '畸形 data（非数值）→ 空态不渲染坏图')
ok(donutIsBlank(null) === true, 'donutInput null → 空态')
ok(donutIsBlank({ slices: [{ name: '人审等待', value: 0, human: true }], totalMin: 0, humanRatio: 0, degraded: false }) === true, '全零 slices → 空态')
ok(donutIsBlank({ slices: [{ name: '机器', value: 3.5, human: false }], totalMin: 3.5, humanRatio: 0, degraded: false }) === false, '非零 slices → 可绘')

/* C. sanitizeMetricsResponse */
section('C sanitizeMetricsResponse reason/容错')
{
  const r = sanitizeMetricsResponse({ kpis: { tickets: 1, closed: 0, avg_delivery_min: 0, tokens_total: 0 }, charts: {}, generated_at: 'x', cache: {}, reason: '降级'.repeat(500) })
  ok(r.error === null && r.reason.length === 600, `reason 承载 + 600 封顶（实得 ${r.reason.length}）`)
  const r2 = sanitizeMetricsResponse(null)
  ok(r2.error !== null && r2.reason === '', '非对象响应 → error + reason 空串')
  const r3 = sanitizeMetricsResponse({ error: '窗口非法' })
  ok(r3.error === '窗口非法' && r3.reason === '', '4xx error 形状 → reason 空')
  const r4 = sanitizeMetricsResponse({ kpis: 'bad', charts: { primary: { kind: 'hBar', title: 't', categories: ['a'], series: [{ name: 'n', data: [1] }], drill: true } } })
  ok(r4.kpis.tickets === 0 && r4.primary !== null, '坏 kpis 容错 + 好 spec 保留')
}

console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILED'}: ${passed} passed, ${failed} failed`)
process.exit(failed > 0 ? 1 : 0)
