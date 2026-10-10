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

/* H t261009-79 修复锁：slim-pipe 场景输入的模型级重放（P7/P3d/P9/T5/T2b）。
 * 夹具形状镜 integration/t261008-23/lib_fix23.mjs fixtureTimeline()（每段带引擎
 * _finish 形状的 done 行、merge 只留 running 开窗 + closed 收尾）；本节在模型层
 * 锁住浏览器场景点名的人脸，集成闸的浏览器重跑是终审证据。 */
import { readFileSync as rf } from 'node:fs'
const fixSrc = rf(new URL('../../../../integration/t261008-23/lib_fix23.mjs', import.meta.url), 'utf8')
ok(/state:\s*'done'/.test(fixSrc), 'fixture source lock: lib_fix23 fixtureTimeline carries explicit done rows (P7 input truth)')
const SD = 1_789_440_000_000 // the slim-pipe fixture epoch family (lib_fix23 T0)
const isoAt = (m) => new Date(SD + m * MIN).toISOString()
const dn = (m, stage) => ({ at: isoAt(m), stage, state: 'done', reason: 'stage finished' })
const STAGES = ['create_plan', 'review_plan', 'implement', 'design_integration_tests', 'ui_evidence',
  'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check', 'merge']
const slimTopo = {
  template: 'dev-lane', name: 'dev lane',
  nodes: STAGES.map((id) => ({ id, label: id, role: 'developer', kind: id === 'merge' ? 'human' : 'agent' })),
  edges: [['create_plan', 'review_plan'], ['review_plan', 'implement'], ['review_plan', 'design_integration_tests'],
    ['implement', 'ui_evidence'], ['design_integration_tests', 'ui_evidence'], ['ui_evidence', 'run_integration_tests'],
    ['run_integration_tests', 'arbitrate'], ['run_integration_tests', 'acceptance_walkthrough'],
    ['arbitrate', 'merge_check'], ['acceptance_walkthrough', 'merge_check'], ['merge_check', 'merge']],
  groups: [
    { id: 'g1', members: ['implement', 'design_integration_tests'], phase: 'p1' },
    { id: 'g2', members: ['arbitrate', 'acceptance_walkthrough'], phase: 'p2' },
  ],
}
const slimTimeline = [
  { at: isoAt(0), stage: 'create_plan', state: 'running', reason: 'plan written' }, dn(1, 'create_plan'),
  { at: isoAt(1), stage: 'review_plan', state: 'running', reason: 'review passed' }, dn(5, 'review_plan'),
  { at: isoAt(5), stage: 'implement', state: 'running', reason: 'implemented' }, dn(6, 'implement'),
  { at: isoAt(6), stage: 'design_integration_tests', state: 'running', reason: 'tests designed' }, dn(15, 'design_integration_tests'),
  { at: isoAt(15), stage: 'ui_evidence', state: 'running', reason: 'captures attached' }, dn(15.5, 'ui_evidence'),
  { at: isoAt(15.5), stage: 'run_integration_tests', state: 'running', reason: 'suite green' }, dn(30.5, 'run_integration_tests'),
  { at: isoAt(30.5), stage: 'arbitrate', state: 'running', reason: 'arbitrated' }, dn(35, 'arbitrate'),
  { at: isoAt(35), stage: 'acceptance_walkthrough', state: 'running', reason: 'walked through' }, dn(38.5, 'acceptance_walkthrough'),
  { at: isoAt(38.5), stage: 'merge_check', state: 'running', reason: 'checks green' }, dn(39.5, 'merge_check'),
  { at: isoAt(39.5), stage: 'merge', state: 'running', reason: 'merged' },
  { at: isoAt(45), stage: 'merge', state: 'closed', reason: '' },
]
for (const nowMs of [SD + 50 * MIN, Date.now()]) {
  const sm = buildLaneMap(slimTopo, { status: 'RUNNING', workflow_id: 'dev-lane', stage: 'merge', stage_state: 'running',
    meta: { parallel_stages: [['implement', 'design_integration_tests'], ['arbitrate', 'acceptance_walkthrough']] },
    timeline: slimTimeline }, { nowMs })
  const ss = laneMapScene(sm)
  const bars = ss.bars.filter(b => b.track === 'main' || b.track === 'partner')
  // P7 状态=填充：done 22% 浅填充 ≥4、当前段实色 ≥1（全链 done + merge 在跑）。
  const tinted = bars.filter(b => Math.abs(b.fillOpacity - 0.22) <= 0.03).length
  const solid = bars.filter(b => Math.abs(b.fillOpacity - 1) <= 0.02).length
  ok(tinted >= 4 && solid >= 1, `P7 state-by-fill on the slim-pipe input: tinted=${tinted} solid=${solid}`)
  // P3d 同级相邻标签不压字（夹具时刻与真实 now 双锚）。
  const mlab = ss.labels.filter(l => l.track === 'main').sort((p, q) => p.x - q.x)
  const overlapSlim = [0, 1].some(lv => mlab.filter(l => l.level === lv).some((l, i, arr) =>
    i > 0 && arr[i - 1].x + arr[i - 1].text.length * 4.5 / 2 > l.x - l.text.length * 4.5 / 2))
  ok(!overlapSlim, `P3d no same-level label overlap at nowMs=${nowMs === SD + 50 * MIN ? 'fixture' : 'real'}`)
  // P9 chrome：头部 elapsed 词面 + 起止两个 hh:mm 时钟。
  ok(sm.header.elapsedText.length > 0, 'P9 header elapsed text present')
  ok(sm.header.startClock !== null && sm.header.endClock !== null && /\d{2}:\d{2}/.test(sm.header.startClock) && /\d{2}:\d{2}/.test(sm.header.endClock),
    `P9 axis clocks render (start=${sm.header.startClock} end=${sm.header.endClock})`)
  // T2b 虚线窗：SVG rect 语义——高跨两道（渲染层补 dasharray + fill none）。
  const dashedWins = ss.windows.filter(w => w.h > 20)
  ok(dashedWins.length >= 2, `T2b dashed windows around both tracks (windows=${ss.windows.length})`)
  // T5 菱形：渲染层 d（绝对坐标、closed fold）在 60 字符窗内满足场景正则。
  const diaBar = ss.bars.find(b => b.diamond && b.track === 'main')
  const diaD = diaBar
    ? `M${diaBar.x + 1.5} ${diaBar.y + diaBar.h / 2} L${diaBar.x + 5} ${diaBar.y + diaBar.h / 2 + 3.5} L${diaBar.x + 8.5} ${diaBar.y + diaBar.h / 2} L${diaBar.x + 5} ${diaBar.y + diaBar.h / 2 - 3.5} Z`
    : ''
  ok(/l\s*-?[\d.]+\s+-?[\d.]+/i.test(diaD.slice(0, 60)) && /z/i.test(diaD.slice(0, 60)),
    'T5 diamond closed-fold regex passes WITHIN a 60-char window (rounding landed)')
  // 坐标干净：全场景数值属性零长浮点尾（r2 修复面）。
  const nums = JSON.stringify(ss).match(/\d+\.\d{3,}/g) || []
  ok(nums.length === 0, `scene coordinates carry no long float tails (found ${nums.slice(0, 3).join(',')})`)
}

console.log(`\nLANE_MAP_PIPE ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
