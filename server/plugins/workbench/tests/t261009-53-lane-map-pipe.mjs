/**
 * tests/t261009-53-lane-map-pipe.mjs —— 泳道图细管道几何 UT（t261009-53）。
 *
 * 直跑：node server/plugins/workbench/tests/t261009-53-lane-map-pipe.mjs
 * 真源：notes/discussions/261004-concurrency-limit-mock.html laneMap(t)
 * （设计稿 §7.6 判据 1-8）。覆盖（ticket 验收口径，语义锚非类名/序号）：
 *   A. 同一条基线细条：主道每条 y/h 恒等（12）、rx=3 语义（渲染层）；段宽
 *      仍 ∝ v5 权重（t261008-23 不回退）；伙伴条在第二道、宽=窗×min(1,ratio)。
 *   B. 标签浮在管道上方两级（基线-4/-13 交错）、middle 锚、夹进画布、
 *      耗时与 ×N 同标签；同级相邻标签不压字（近似宽=字符数×4.5px@8px 字号，
 *      review 意见 1：两级交错即 mock 的唯一防压字机制，此处加同级不重叠断言）。
 *   C. 人门菱形：条头（条左端）菱形位（criterion 5）。
 *   D. 并行：伙伴条第二道、虚线窗围两道（y 从基线-4 到伙伴条底+4）、∥ 记号。
 *   E. 状态：done=0.22 浅填充、running=实色+跨道游标、todo=灰、skipped=虚线空框。
 *   F. 畸形输入：空 timeline/零总重不抛、场景仍成立（畸形输入纪律）。
 *   G. 通用性（场景半）：fixture-two-step 同一场景构建器，零 dev-lane 词；
 *      逐轮证据折叠进段 title（轮格退休但打回原因不丢——review 意见 2）；
 *      「曾受阻」角标仍以 everTitle 在场（review 意见 3）。
 * 全程纯函数直跑，不碰 3099、不起 console。
 */
import assert from 'node:assert/strict'
import { buildLaneMap, laneMapScene, LM_SCENE, LANE_NOMINAL_MS } from '../src/client/lane-map-model.ts'

let passed = 0, failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const T0 = 1_700_000_000_000
const MIN = 60_000
const NOW = T0 + 80 * MIN

// 四段主道（含一个人门收尾）+ 一个并行叉：a(60m) → b(10m) → (c ∥ d) → e(human)
const TOPO = {
  version: 'topology-v1',
  template: 'dev-lane',
  name: 'dev lane',
  nodes: [
    { id: 'a', label: 'A', role: 'developer', kind: 'agent', parts: ['agent'] },
    { id: 'b', label: 'B', role: 'integration', kind: 'agent', parts: ['agent'] },
    { id: 'c', label: 'C', role: 'developer', kind: 'agent', parts: ['agent'] },
    { id: 'd', label: 'D', role: 'integration', kind: 'agent', parts: ['agent'] },
    { id: 'e', label: 'E', role: 'you', kind: 'human', parts: [] },
  ],
  edges: [['a', 'b'], ['b', 'c'], ['b', 'd'], ['c', 'e'], ['d', 'e']],
  groups: [{ id: 'par_cd', members: ['c', 'd'], phase: 'par_cd' }],
}
const at = m => new Date(T0 + m * MIN).toISOString()
const timeline = [
  { at: at(0), stage: 'a', state: 'running' },
  { at: at(60), stage: 'a', state: 'done' },
  { at: at(60), stage: 'b', state: 'running' },
  { at: at(70), stage: 'b', state: 'done' },
  { at: at(70), stage: 'c', state: 'running' },
  { at: at(76), stage: 'c', state: 'done' },
  { at: at(70), stage: 'd', state: 'running' },
  { at: at(80), stage: 'd', state: 'done' },
  { at: at(80), stage: 'e', state: 'running' },
]
const handoffs = [
  { stage: 'a', ts: (T0 + 60 * MIN) / 1000 },
  { stage: 'b', ts: (T0 + 70 * MIN) / 1000 },
  { stage: 'c', ts: (T0 + 76 * MIN) / 1000 },
  { stage: 'd', ts: (T0 + 80 * MIN) / 1000 },
]

const model = buildLaneMap(TOPO, { status: 'open', timeline, handoffs }, { nowMs: NOW })
ok(model !== null, 'model builds')
const scene = laneMapScene(model)

/* A 一条基线细条 + v5 宽度不回退 */
const main = scene.bars.filter(b => b.track === 'main')
ok(main.length === 4, `four main bars (got ${main.length})`)
ok(main.every(b => b.y === LM_SCENE.AY && b.h === LM_SCENE.AH), `every main bar sits on ONE baseline at h=${LM_SCENE.AH} (the mock's 12px slim bar)`)
ok(main.every(b => b.w > 0), 'every main bar has a positive width')
const xs = main.map(b => b.x)
ok(xs.every((x, i) => i === 0 || x > xs[i - 1]), 'bars read left to right in topology order')
const weights = ['a', 'b', 'par_cd'].map(id =>
  id === 'par_cd' ? model.groups.par_cd.windowMs : model.nodes[id].weightMs)
ok(weights[0] > weights[1] && main[0].w > main[1].w, 'width ordering follows the weight ordering (v5 survives)')
const mainGroup = main.find(b => b.stageId === 'c')
const win = scene.windows.find(wn => wn.groupId === 'par_cd')
ok(mainGroup && win && mainGroup.w === win.w - 8, 'the main bar spans the whole window (the partner takes only its own share)')

const partner = scene.bars.find(b => b.track === 'partner')
ok(partner && partner.y === LM_SCENE.BY && partner.h === LM_SCENE.BH, 'the partner bar sits on the SECOND track (below the main one)')
ok(partner.stageId === 'd', 'the partner bar is the window partner (d)')
ok(mainGroup && win && Math.abs(partner.w - Math.max(LM_SCENE.MINW, win.w - 8) * Math.min(1, partnerWeight() / win.windowMs)) < 2,
  'partner width = window share clamped by min(1, partner/window)')
function partnerWeight() { return model.nodes.d.weightMs }

/* B 标签：两级、middle 锚、夹边、耗时×N 同行、同级不压字 */
const mlabels = scene.labels.filter(l => l.track === 'main')
ok(mlabels.length === 4, `four main labels (got ${mlabels.length})`)
ok(mlabels.every(l => l.y === LM_SCENE.LABEL_LO || l.y === LM_SCENE.LABEL_HI), 'labels sit in the two floating levels above the baseline')
ok(mlabels.every(l => l.y < LM_SCENE.AY - 1), 'no label is painted on top of a bar')
const aLabel = mlabels[0]
ok(/^a\b/.test(aLabel.text) && /1h|60m/.test(aLabel.text), `label text = name + duration (got "${aLabel.text}")`)
ok(mlabels.every(l => l.anchor === 'middle'), 'main labels are middle-anchored on their bar')
ok(mlabels.every(l => l.x >= LM_SCENE.CLAMP_MIN && l.x <= LM_SCENE.CLAMP_MAX), 'labels are clamped into the canvas')
ok(Math.abs(aLabel.x - (LM_SCENE.PAD + main[0].w / 2)) < 1, 'a wide stage label is centred on its own bar')
ok(scene.leaders.length === mlabels.length && scene.leaders.every(l => l.y1 < LM_SCENE.AY && l.y2 === LM_SCENE.AY - 1), 'a dotted leader drops from each label level to the bar top')
// 同级相邻标签不压字（近似宽 = 字符数 × 4.5px @ 8px；review 意见 1）
const levels = [0, 1].map(lv => mlabels.filter(l => l.level === lv).sort((p, q) => p.x - q.x))
const overlap = levels.some(arr => arr.some((l, i) => {
  if (i === 0) return false
  const prev = arr[i - 1]
  return prev.x + prev.text.length * 4.5 / 2 > l.x - l.text.length * 4.5 / 2
}))
ok(!overlap, 'adjacent same-level labels do not overlap (approx width chars×4.5px @ 8px)')

/* C 人门菱形坐在条头 */
const humanBar = main.find(b => b.kind === 'human')
ok(humanBar && humanBar.stageId === 'e', 'the human-gate stage has a main bar')
const headDiamond = scene.diamonds.find(dd => Math.abs(dd.x - (humanBar.x + 5)) < 0.01 && Math.abs(dd.y - (humanBar.y + humanBar.h / 2)) < 0.01)
ok(headDiamond !== undefined, 'the diamond sits at the LEFT END (head) of the human bar - not inside a box')

/* D 并行窗围两道 + ∥ 记号 */
ok(win && Math.abs(win.y - (LM_SCENE.AY - 4)) < 0.01
  && Math.abs((win.y + win.h) - (LM_SCENE.BY + LM_SCENE.BH + 4)) < 0.01,
  'the dashed window surrounds BOTH tracks (from above the main bar to below the partner bar)')
ok(scene.parMarks.length === 1 && scene.parMarks[0].x > win.x && scene.parMarks[0].y < LM_SCENE.BY + LM_SCENE.BH,
  'the ∥ mark rides the window head')
const plabel = scene.labels.find(l => l.track === 'partner')
ok(plabel && plabel.y > LM_SCENE.BY + LM_SCENE.BH && plabel.x >= win.x, 'the partner label sits below the partner track')

/* E 状态用填充 */
const doneBar = main.find(b => b.stageId === 'a')
ok(doneBar.fillOpacity === 0.22, 'done = 22% tint of the kind colour')
const runningBar = main.find(b => b.stageId === 'e')
ok(runningBar.fillOpacity === 1 && runningBar.now, 'running = solid fill on the current segment')
ok(scene.cursor && Math.abs(scene.cursor.x - (runningBar.x + runningBar.w)) < 0.01
  && scene.cursor.y1 < LM_SCENE.AY && scene.cursor.y2 > LM_SCENE.BY + LM_SCENE.BH,
  'the now cursor is a vertical line spanning BOTH tracks at the current segment edge')
ok(scene.bars.every(b => b.dashed === (b.skipped === true)), 'skipped = dashed empty (no fill), others solid-stroked')
const unstarted = buildLaneMap(TOPO, { status: 'open', timeline: [] }, { nowMs: NOW })
const sceneTodo = laneMapScene(unstarted)
ok(sceneTodo.bars.every(b => b.vis === 'todo' && !b.dashed), 'not started = grey todo bars across the board')

/* F 畸形输入不抛 */
let threw = ''
try {
  const bad = buildLaneMap(TOPO, { status: 'open', timeline: [null, 42, { stage: 7 }, 'x'], handoffs: [{ ts: 'x' }] }, { nowMs: NOW })
  const bs = laneMapScene(bad)
  ok(bs.bars.filter(b => b.track === 'main').length === 4 && bs.bars.every(b => b.vis === 'todo' || b.now), 'malformed timeline → nominal scene, no throw (fallback-now item aside, all todo)')
  const zero = buildLaneMap(TOPO, { status: 'open', timeline: [] }, { nowMs: NOW })
  const zs = laneMapScene(zero)
  ok(zs.width > 0 && zs.bars.every(b => b.w > 0), 'zero measured weight (all nominal) still yields positive bar widths')
} catch (e) { threw = String(e) }
ok(threw === '', `malformed inputs do not throw (got ${threw.slice(0, 60)})`)
const nominalBar = sceneTodo.bars[0]
ok(Math.abs(model.nodes.a.weightMs - 60 * MIN) < 1000 && unstarted.nodes.a.weightMs === LANE_NOMINAL_MS,
  'weights unchanged from the model (this ticket touches geometry only)')

/* G 通用性 + 轮证据折叠 + 曾受阻角标 */
const two = buildLaneMap(
  {
    template: 'fixture-two-step',
    nodes: [
      { id: 's1', label: 'S1', role: 'r', kind: 'gate', parts: [] },
      { id: 's2', label: 'S2', role: 'r', kind: 'human', parts: [] },
    ],
    edges: [['s1', 's2']],
    groups: [],
  },
  { status: 'open', timeline: [{ at: at(0), stage: 's1', state: 'running' }] },
  { nowMs: NOW },
)
const twoScene = laneMapScene(two)
ok(twoScene.bars.length === 2 && twoScene.windows.length === 0, 'a linear two-step template renders through the same scene builder')
const twoText = JSON.stringify(twoScene)
ok(!/dev[-_]lane|implement|arbitrate|walkthrough/i.test(twoText), 'scene face carries zero dev-lane business words')

const reworkTimeline = [
  { at: at(0), stage: 'a', state: 'running' },
  { at: at(5), stage: 'a', state: 'rework', reason: '越界' },
  { at: at(10), stage: 'a', state: 'running' },
  { at: at(20), stage: 'a', state: 'done' },
]
const rw = buildLaneMap({ template: 't', nodes: [{ id: 'a', label: 'A', role: 'r', kind: 'agent', parts: [] }], edges: [], groups: [] },
  { status: 'open', timeline: reworkTimeline, gens: {} }, { nowMs: T0 + 30 * MIN })
const rwScene = laneMapScene(rw)
ok(rwScene.bars.length === 1 && /×\s*2/.test(rwScene.labels[0].roundBadge || ''), `rework rounds collapse into the ×N badge (got "${rwScene.labels[0].roundBadge}")`)
ok(/越界/.test(rwScene.bars[0].title), 'the first round rework reason survives inside the segment hover title (round chips retired, evidence kept)')
ok(rwScene.labels[0].everTitle === undefined, 'no ever-blocked badge without a resolved blocked history')

console.log(`\nLANE_MAP_PIPE ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
