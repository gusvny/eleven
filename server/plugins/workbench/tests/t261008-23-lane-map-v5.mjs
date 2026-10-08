/**
 * tests/t261008-23-lane-map-v5.mjs —— 泳道图 v5 时间占比 UT（t261008-23）。
 *
 * 直跑：node server/plugins/workbench/tests/t261008-23-lane-map-v5.mjs
 * 覆盖（ticket 验收口径，语义锚非类名/序号）：
 *   A. 段宽权重 ∝ 时长：weights NOT all equal，比例对表 lane-durations 同源
 *      权重（固定 nowMs 注入=确定性，review 意见 5）；容差取固定定宽实现
 *      不可能满足的区间（此处权重即模型值，比例容差 1e-9）。
 *   B. 未开始段=名义权重 LANE_NOMINAL_MS（mock「未开始的段按名义时长占位」）。
 *   C. 并行窗：windowMs=成员最大权重（一窗）；伙伴带夹取 min(1, partner/window)
 *      （review 意见 4：partner 比 head 长不溢出）——经渲染器几何锚 lmBandPct
 *      的等价断言：data-band/data-window-ms 语义锚由 DOM 层场景覆盖，此处锁模型量。
 *   D. 畸形 timeline → 全段名义权重、不抛（review 意见 3：借用实现的继承故障面 +
 *      本层新增面）。
 *   E. 渲染器通用性（模型半）：fixture-two-step 线性拓扑同组件建模，零 dev-lane 词。
 * 全程纯函数直跑，不碰 3099、不起 console。
 */
import assert from 'node:assert/strict'
import { buildLaneMap } from '../src/client/lane-map-model.ts'
import { LANE_NOMINAL_MS } from '../src/client/lane-map-model.ts'

let passed = 0, failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const TOPO = {
  version: 'topology-v1',
  template: 'dev-lane',
  name: 'dev lane',
  nodes: [
    { id: 'a', label: 'A', role: 'developer', kind: 'agent', parts: ['agent'] },
    { id: 'b', label: 'B', role: 'integration', kind: 'agent', parts: ['agent'] },
    { id: 'c', label: 'C', role: 'developer', kind: 'agent', parts: ['agent'] },
    { id: 'd', label: 'D', role: 'integration', kind: 'agent', parts: ['agent'] },
  ],
  edges: [['a', 'b'], ['b', 'c'], ['b', 'd']],
  groups: [{ id: 'par_cd', members: ['c', 'd'], phase: 'par_cd' }],
}

// a 跑了 60min，b 跑了 10min；c 跑了 6min（收口），d 还开着（running，nowMs 定值收口）。
const T0 = 1_700_000_000_000
const MIN = 60_000
const timeline = [
  { at: new Date(T0).toISOString(), stage: 'a', state: 'running' },
  { at: new Date(T0 + 60 * MIN).toISOString(), stage: 'b', state: 'running' },
  { at: new Date(T0 + 60 * MIN).toISOString(), stage: 'a', state: 'done' },
  { at: new Date(T0 + 70 * MIN).toISOString(), stage: 'c', state: 'running' },
  { at: new Date(T0 + 70 * MIN).toISOString(), stage: 'b', state: 'done' },
  { at: new Date(T0 + 76 * MIN).toISOString(), stage: 'c', state: 'done' },
  { at: new Date(T0 + 70 * MIN).toISOString(), stage: 'd', state: 'running' },
]
const handoffs = [
  { stage: 'a', ts: (T0 + 60 * MIN) / 1000 },
  { stage: 'b', ts: (T0 + 70 * MIN) / 1000 },
  { stage: 'c', ts: (T0 + 76 * MIN) / 1000 },
]
const NOW = T0 + 80 * MIN

const m = buildLaneMap(TOPO, { status: 'open', timeline, handoffs }, { nowMs: NOW })
ok(m !== null, 'model builds')
const a = m.nodes.a, b = m.nodes.b, c = m.nodes.c, d = m.nodes.d

/* A 权重 ∝ 时长（同源对表：a=60min b=10min c=6min d=10min(running elapsed)） */
ok(a.weightMs === 60 * MIN, `a weight=60min measured (got ${a.weightMs})`)
ok(b.weightMs === 10 * MIN, `b weight=10min measured (got ${b.weightMs})`)
ok(Math.abs(c.weightMs - 6 * MIN) < 1000, `c weight≈6min measured (got ${c.weightMs})`)
ok(Math.abs(d.weightMs - 10 * MIN) < 1000, `d weight=10min running elapsed at fixed nowMs (got ${d.weightMs})`)
ok(a.durSource === 'measured' && d.durSource === 'running', `durSource measured/running (got ${a.durSource}/${d.durSource})`)
const ws = [a.weightMs, b.weightMs, c.weightMs, d.weightMs]
ok(new Set(ws).size > 1, 'weights are NOT all equal (fixed-width impl cannot satisfy this)')
ok(Math.abs(a.weightMs / b.weightMs - 6) < 1e-9, 'proportionality ratio matches the duration source used (60/10=6, tolerance 1e-9)')

/* B 并行窗（一窗，两带） */
const g = m.groups.par_cd
ok(g !== undefined && g.members.length === 2, 'parallel group present with two members')
ok(g.windowMs === Math.max(c.weightMs, d.weightMs), 'window weight = max of member weights (one window)')
ok(g.members[0].weightMs !== g.members[1].weightMs, 'the two bands carry different weights')

/* C 名义权重：未开始段 */
const m2 = buildLaneMap(TOPO, { status: 'open', timeline: [] }, { nowMs: NOW })
ok(m2 !== null && m2.nodes.a.weightMs === LANE_NOMINAL_MS, 'unstarted stage takes the nominal weight')
ok(m2.nodes.a.durSource === 'nominal', 'unstarted durSource=nominal')
ok(m2.groups.par_cd.windowMs === LANE_NOMINAL_MS, 'unstarted group window = nominal (mock: not eaten by the first stage)')

/* D 畸形输入：不抛、全名义 */
let threw = ''
try {
  const bad = buildLaneMap(TOPO, { status: 'open', timeline: [null, 42, { stage: 7 }, { stage: 'a' }, 'x'], handoffs: [{ ts: 'x' }, null] }, { nowMs: NOW })
  ok(bad !== null && Object.values(bad.nodes).every(n => n.weightMs === LANE_NOMINAL_MS), 'malformed timeline → all nominal weights, no throw')
} catch (e) { threw = String(e) }
ok(threw === '', `malformed input does not throw (got ${threw.slice(0, 60)})`)

/* D2 复现夹具（ticket 实报的形状）：at 非法 ISO 的条目跳过（lane-durations 纪律继承） */
const badIso = buildLaneMap(TOPO, { status: 'open', timeline: [{ at: 'not-a-date', stage: 'a', state: 'running' }], handoffs }, { nowMs: NOW })
ok(badIso.nodes.a.weightMs === LANE_NOMINAL_MS, 'invalid ISO at → skipped, nominal weight (no fabricated duration)')

/* E 通用性（模型半）：两步线性模板同组件建模 */
const two = buildLaneMap(
  { template: 'fixture-two-step', nodes: [{ id: 's1', label: 'S1', role: 'r', kind: 'gate', parts: [] }, { id: 's2', label: 'S2', role: 'r', kind: 'human', parts: [] }], edges: [['s1', 's2']], groups: [] },
  { status: 'open', timeline: [{ at: new Date(T0).toISOString(), stage: 's1', state: 'running' }] },
  { nowMs: NOW },
)
ok(two !== null && two.nodes.s1.weightMs === NOW - T0 && two.nodes.s2.weightMs === LANE_NOMINAL_MS, 'non-dev-lane template models through the same component (open window ticks to the injected nowMs)')
const modelText = JSON.stringify({ ...two, topology: undefined })
ok(!/dev[-_]lane|implement|arbitrate|walkthrough/i.test(modelText), 'model face carries zero dev-lane business words')

console.log(`\nLANE_MAP_V5 ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
