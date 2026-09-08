/**
 * lane-stage-durations —— t260901-12「泳道图节点直显耗时（M1b）」推导函数行为测试
 * （黑盒：消费 timeline/handoffs fixture，只验语义不验实现细节）。
 *
 * 直跑：node integration/baselines/lane-stage-durations.mjs（cwd=泳道根，零依赖）。
 *
 * 被测契约（integration 侧约定，create_plan v4 经 review_plan 第 4 轮通过）：
 *   - 推导函数导出 deriveStageDurations 与 fmtDur，住在 server/plugins/workbench/src/client/
 *     下的**纯 .ts 模块**（node 无法 import .tsx；index.tsx 只做消费不做推导）。
 *   - 签名 deriveStageDurations(timeline, order, handoffs?, opts?: {nowMs?, closedTs?})
 *     → Record<stageId, {stage, rounds: {fromMs, toMs|null}[], humanWaits: {fromMs, toMs|null}[]}>；
 *     返回键 ⊆ order，模板外 stage id 不泄漏进键。
 *   - 轮收口五级链（每 stage 第 n 轮，窗=(第 n 条 running mark, 下一开窗 mark]，末轮上界 +∞）：
 *     1. 本 stage handoff 窗内最大 ts（handoff.ts 为 epoch **秒**，×1000 转 ms 后再比较；
 *        handoff 键 'acceptance' 映射到 lane id 'acceptance_walkthrough'，映射前过滤畸形条目）；
 *     2. {stage:'merge', state:'closed'} mark：收其他 stage 开放窗 + merge 末轮兜底；
 *     3. 下一条任意 stage 的 running mark；
 *     4. closed 单 detail.updated（epoch 秒 ×1000），缺失 → toMs=null；
 *     5. 未 closed → toMs=null（开放窗，running/awaiting-human 视觉态由 UI 用 nowMs 走秒）。
 *   - awaiting-human 段：awaiting mark 至其后第一条 mark（任意 stage 任意态）；无后继时按
 *     closed 收口链（merge/closed mark → updated）收口，未 closed → null（实时）。
 *   - 轮=相邻 running mark 墙钟段，AH/blocked mark 不关轮（签字等待计入所在轮，人等段单列）。
 *   - 畸形输入：timeline 缺字段/空串/非法 ISO/模板外 id 跳过；handoff ts 非有限数/stage 非串
 *     跳过（映射前）；handoffs 非数组按 [] 处理；乱序 mark 先按 ms 排序再推导；空 timeline → {}。
 *   - fmtDur(ms|null)：<60s「Xs」；<60m「Xm Ys」（0 段省略）；≥1h「Xh Ym」；null/负数/NaN→「—」。
 *
 * 覆盖（用户可感知行为 × 故障面）：
 *   U1 done 定值（S1）；U2 running 开放窗（S7a）；U3 人等实时/历史（S7）；U4 tooltip 拆轮
 *   数据源 rounds/humanWaits（S3/S4）；U5 并行分叉独立计时（S2，本票核心回归锚）；
 *   U6 merge 签字等待计入轮+人等单列（S3，N4a 声明互证）；U7 rework 多轮/冲突取最大（S4）；
 *   U8 畸形输入三态（S8）；U9 秒/毫秒单位锚定（S9，P0 修正版对应值）；U10 时钟回拨负差（S11）；
 *   U11 时长格式化（S10）；U12 closed 兜底优先级链（S6）。
 * 资源回收面无 node 可测条目：useNow interval 生命周期（卸载/无活跃清表）是 UI 侧资源，
 * 归 ui_evidence 段截图 + 人审代码清单（禁常驻定时器），本套件不重复守。
 *
 * 安全红线：纯本地 fixture，不碰 3099/Temporal/网络。
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')
const CLIENT_SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client')

let passed = 0, failed = 0, skipped = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------------------------------------- 被测模块解析 */
section('resolve deriveStageDurations/fmtDur module')
const candidates = readdirSync(CLIENT_SRC).filter(f => f.endsWith('.ts') && !f.endsWith('.d.ts'))
let derive = null, fmtDur = null, deriveFrom = ''
for (const f of candidates) {
  const p = join(CLIENT_SRC, f)
  try {
    const mod = await import(pathToFileURL(p).href + '?t=' + Date.now())
    if (typeof mod.deriveStageDurations === 'function' && typeof mod.fmtDur === 'function') {
      derive = mod.deriveStageDurations; fmtDur = mod.fmtDur; deriveFrom = f; break
    }
  } catch { /* 该文件不可 import（含平台依赖等）则继续扫描 */ }
}
if (!derive || !fmtDur) {
  console.log('  FAIL src/client/ 下找不到同时导出 deriveStageDurations 与 fmtDur 的纯 .ts 模块')
  console.log('       （node 无法 import .tsx；推导函数须独立成纯 ts 模块，见本文件头契约）')
  console.log(`\nSUMMARY pass=0 skip=0 fail=1`)
  process.exit(1)
}
console.log(`  ok resolve deriveStageDurations+fmtDur @ src/client/${deriveFrom}`)

/* ---------------------------------------------------------------- 工具与常量 */
const ORDER = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge', 'suggest_next']
const B = Date.parse('2026-09-01T00:00:00.000Z') // 整分钟，秒级 epoch 可整除
const iso = ms => new Date(ms).toISOString()
const sec = ms => ms / 1000 // epoch 秒（handoff.ts / closedTs 的单位）
const RUN = 'running', AH = 'awaiting-human', CLOSED = 'closed'
const tle = (ms, stage, state, reason = '') => ({ at: iso(ms), stage, state, reason })
const ho = (ms, stage) => ({ stage, ts: sec(ms), summary: '完成' })

/** 取 stage 的轮/人等段；缺 stage 返回 undefined 供调用方断言。 */
const roundsOf = (out, stage) => out[stage]?.rounds
const waitsOf = (out, stage) => out[stage]?.humanWaits ?? []
/** 断言单轮/单段的精确窗口。 */
function expectWin(win, fromMs, toMs, label) {
  ok(!!win, `${label}: 存在`)
  if (!win) return
  ok(win.fromMs === fromMs, `${label}: fromMs=${win.fromMs} want=${fromMs}`)
  ok(win.toMs === toMs, `${label}: toMs=${win.toMs} want=${toMs}`)
}

/* ---------------------------------------------------------------- S1 done 定值（U1） */
section('S1 closed 单全链：每节点定值（handoff 收口）')
{
  const timeline = [tle(B, 'create_plan', RUN), tle(B + 60000, 'review_plan', RUN),
    tle(B + 120000, 'implement', RUN), tle(B + 180000, 'design_integration_tests', RUN)]
  const handoffs = [ho(B + 30000, 'create_plan'), ho(B + 90000, 'review_plan'),
    ho(B + 150000, 'implement'), ho(B + 210000, 'design_integration_tests')]
  const out = derive(timeline, ORDER, handoffs, { nowMs: B + 999000, closedTs: sec(B + 240000) })
  const keys = Object.keys(out)
  ok(keys.every(k => ORDER.includes(k)), `返回键 ⊆ order（got ${JSON.stringify(keys)}）`)
  expectWin(roundsOf(out, 'create_plan')?.[0], B, B + 30000, 'create_plan 轮1')
  expectWin(roundsOf(out, 'review_plan')?.[0], B + 60000, B + 90000, 'review_plan 轮1')
  expectWin(roundsOf(out, 'implement')?.[0], B + 120000, B + 150000, 'implement 轮1')
  expectWin(roundsOf(out, 'design_integration_tests')?.[0], B + 180000, B + 210000, 'dit 轮1')
}

/* ---------------------------------------------------------------- S2 并行分叉独立计时（U5 核心锚） */
section('S2 并行分叉：implement/dit 各自独立计时（handoff 优先于并行兄弟 mark）')
{
  const timeline = [tle(B, 'implement', RUN), tle(B + 2000, 'design_integration_tests', RUN),
    tle(B + 3700000, 'ui_evidence', RUN)]
  const handoffs = [ho(B + 3600000, 'implement'), ho(B + 1800000, 'design_integration_tests')]
  const out = derive(timeline, ORDER, handoffs, { nowMs: B + 3700000 })
  expectWin(roundsOf(out, 'implement')?.[0], B, B + 3600000,
    'implement 轮1（闭合于本 stage handoff，非 dit 的 running mark≈0s）')
  expectWin(roundsOf(out, 'design_integration_tests')?.[0], B + 2000, B + 1800000, 'dit 轮1')
}

/* ---------------------------------------------------------------- S3 merge 签字（U4/U6，N4a 互证） */
section('S3 merge 签字：轮含等待、人等单列、handoff 优先于 closed mark（N4d①）')
{
  const timeline = [tle(B, 'merge', RUN), tle(B + 600000, 'merge', AH, '等人签字'),
    tle(B + 1800000, 'merge', RUN, '人审通过'), tle(B + 2401000, 'merge', CLOSED, 'workflow 完成')]
  const handoffs = [ho(B + 2400000, 'merge')]
  const out = derive(timeline, ORDER, handoffs, { nowMs: B + 2500000 })
  const rs = roundsOf(out, 'merge') ?? []
  ok(rs.length === 2, `merge 两轮（got ${rs.length}）`)
  expectWin(rs[0], B, B + 1800000, 'merge 轮1（跨签字等待，由人审通过 running mark 关窗）')
  expectWin(rs[1], B + 1800000, B + 2400000, 'merge 轮2（handoff 优先于 closed mark）')
  const ws = waitsOf(out, 'merge')
  ok(ws.length === 1, `人等单段（got ${ws.length}）`)
  expectWin(ws[0], B + 600000, B + 1800000, '人等段（AH→人审通过 running）')
  if (rs.length >= 2) ok(rs[0].fromMs < rs[1].fromMs, '轮按时间升序不重叠')
}

/* ---------------------------------------------------------------- S4 rework 多轮 / 冲突取最大（U7） */
section('S4a 打回重进：两轮拆轮，轮2 由 handoff 收口')
{
  const timeline = [tle(B, 'implement', RUN), tle(B + 300000, 'implement', RUN, '打回重进'),
    tle(B + 1300000, 'design_integration_tests', RUN)]
  const handoffs = [ho(B + 1200000, 'implement')]
  const out = derive(timeline, ORDER, handoffs, { nowMs: B + 1300000 })
  const rs = roundsOf(out, 'implement') ?? []
  ok(rs.length === 2, `implement 两轮（got ${rs.length}）`)
  expectWin(rs[0], B, B + 300000, '轮1（重进 mark 关窗）')
  expectWin(rs[1], B + 300000, B + 1200000, '轮2（handoff 关窗，非 dit running mark）')
}
section('S4b 冲突消解：窗内两条本 stage handoff 取最大')
{
  const timeline = [tle(B, 'implement', RUN), tle(B + 1300000, 'design_integration_tests', RUN)]
  const handoffs = [ho(B + 600000, 'implement'), ho(B + 1200000, 'implement')]
  const out = derive(timeline, ORDER, handoffs, { nowMs: B + 1300000 })
  expectWin(roundsOf(out, 'implement')?.[0], B, B + 1200000, 'implement 轮1（取最大 handoff）')
}
section('S4c 口径 3 字面锚：无 handoff 且兄弟 mark 介入两轮之间（spec-literal，交仲裁')
{
  // plan v4 五级链口径 3 原文「下一条**任意 stage** 的 running mark」：
  // implement 轮 1 与轮 2 之间夹 dit 的 running mark → 轮 1 关窗于 dit 的 mark。
  const timeline = [tle(B, 'implement', RUN), tle(B + 2000, 'design_integration_tests', RUN),
    tle(B + 300000, 'implement', RUN, '打回重进')]
  const out = derive(timeline, ORDER, [], { nowMs: B + 400000 })
  const rs = roundsOf(out, 'implement') ?? []
  ok(rs.length === 2, `implement 两轮（got ${rs.length}）`)
  expectWin(rs[0], B, B + 2000, '轮1（spec-literal：关窗于介入的 dit running mark）')
  expectWin(rs[1], B + 300000, null, '轮2（无后继 → 开放窗）')
}

/* ---------------------------------------------------------------- S5 无 handoff 回退（ui_evidence 内联步） */
section('S5 无 handoff 的步：回退下一条 running mark（ui_evidence 型）')
{
  const timeline = [tle(B, 'ui_evidence', RUN), tle(B + 300000, 'run_integration_tests', RUN)]
  const out = derive(timeline, ORDER, [], { nowMs: B + 300000 })
  expectWin(roundsOf(out, 'ui_evidence')?.[0], B, B + 300000, 'ui_evidence 轮1（run_integration_tests mark 关窗）')
}

/* ---------------------------------------------------------------- S6 closed 兜底优先级链（U12） */
section('S6a closed mark：收其他 stage 开放窗 + merge 末轮兜底')
{
  const timeline = [tle(B, 'merge', RUN), tle(B + 30000, 'design_integration_tests', RUN),
    tle(B + 60000, 'merge', CLOSED, 'workflow 完成')]
  const out = derive(timeline, ORDER, [], { nowMs: B + 70000 })
  expectWin(roundsOf(out, 'merge')?.[0], B, B + 60000, 'merge 末轮（无 handoff → closed mark 兜底）')
  expectWin(roundsOf(out, 'design_integration_tests')?.[0], B + 30000, B + 60000,
    'dit 开放窗（closed mark 收其他 stage）')
}
section('S6b closedTs（updated 秒×1000）兜底与缺失 → null')
{
  const tl = [tle(B, 'merge', RUN)]
  const out1 = derive(tl, ORDER, [], { nowMs: B + 90000, closedTs: sec(B + 90000) })
  expectWin(roundsOf(out1, 'merge')?.[0], B, B + 90000, 'merge 末轮（closedTs 兜底）')
  const out2 = derive(tl, ORDER, [], { nowMs: B + 90000 }) // 无 closedTs 且单未 closed
  expectWin(roundsOf(out2, 'merge')?.[0], B, null, 'merge 末轮（无任何收口 → 开放窗 toMs=null）')
}

/* ---------------------------------------------------------------- S7 人等窗：实时 / 历史 / closed 收口（U3/N2） */
section('S7a 人等实时：无后继 mark → toMs=null（UI 用 nowMs 走秒）')
{
  const timeline = [tle(B, 'merge', RUN), tle(B + 60000, 'merge', AH, '等人签字')]
  const out = derive(timeline, ORDER, [], { nowMs: B + 660000 })
  expectWin(waitsOf(out, 'merge')[0], B + 60000, null, '人等开放段（实时）')
  expectWin(roundsOf(out, 'merge')?.[0], B, null, 'merge 轮1 开放（实时）')
}
section('S7b closed 单开放人等段：收口于 closedTs，显定值不随 now 增长（N2）')
{
  const timeline = [tle(B, 'merge', RUN), tle(B + 60000, 'merge', AH, '等人签字')]
  const out = derive(timeline, ORDER, [], { nowMs: B + 660000, closedTs: sec(B + 120000) })
  expectWin(waitsOf(out, 'merge')[0], B + 60000, B + 120000, '人等段 closedTs 收口')
  expectWin(roundsOf(out, 'merge')?.[0], B, B + 120000, 'merge 轮1 closedTs 收口')
}
section('S7c 历史人等段：至其后第一条 mark')
{
  const timeline = [tle(B, 'review_plan', AH, '等人'), tle(B + 60000, 'create_plan', RUN, '打回重进')]
  const out = derive(timeline, ORDER, [], { nowMs: B + 120000 })
  expectWin(waitsOf(out, 'review_plan')[0], B, B + 60000, '人等段（AH→后继 mark）')
}

/* ---------------------------------------------------------------- S8 畸形输入三态（U8） */
section('S8a timeline 畸形：跳过/不炸/不泄漏模板外键/乱序排序')
{
  const timeline = [
    null,
    {},
    { at: 'not-a-date', stage: 'implement', state: RUN },
    { at: iso(B + 5000), stage: 42, state: RUN },
    { at: '', stage: '', state: '' },
    tle(B + 4000, 'acceptance', RUN),            // phase 域模板外 id
    tle(B + 3000, 'parallel_impl_design', RUN),  // phase 域模板外 id
    tle(B + 1200000, 'implement', RUN),          // 乱序：最晚的放最前之后
    tle(B, 'implement', RUN),
  ]
  let out = null, threw = null
  try { out = derive(timeline, ORDER, [ho(B + 600000, 'implement')], { nowMs: B + 1300000 }) }
  catch (e) { threw = e }
  ok(!threw, `不抛错（threw=${threw && threw.message}）`)
  if (out) {
    const foreign = Object.keys(out).filter(k => !ORDER.includes(k))
    ok(foreign.length === 0, `键不泄漏模板外 id（got ${JSON.stringify(foreign)}）`)
    expectWin(roundsOf(out, 'implement')?.[0], B, B + 600000,
      '乱序+畸形混杂后窗口仍正确（排序后推导）')
  }
}
section('S8b handoff 畸形：映射前过滤；非数组按 []；别名键生效')
{
  // acceptance 键映射：合法别名命中
  const tl1 = [tle(B, 'acceptance_walkthrough', RUN), tle(B + 60000, 'merge_check', RUN)]
  const out1 = derive(tl1, ORDER, [{ stage: 'acceptance', ts: sec(B + 30000) }], { nowMs: B + 60000 })
  expectWin(roundsOf(out1, 'acceptance_walkthrough')?.[0], B, B + 30000, 'acceptance 别名映射命中')
  // 别名键但 ts 畸形：映射前过滤 → 不收口，回退下一条 running mark
  const out2 = derive(tl1, ORDER, [{ stage: 'acceptance', ts: NaN }], { nowMs: B + 60000 })
  expectWin(roundsOf(out2, 'acceptance_walkthrough')?.[0], B, B + 60000, 'NaN ts 映射前过滤→回退')
  // 其它畸形条目 + handoffs 整体非数组
  const garbage = [{ stage: 'implement', ts: '123' }, { stage: 42, ts: sec(B + 1) },
    { stage: '', ts: sec(B + 1) }, { ts: sec(B + 1) }]
  let threw = null
  try {
    derive([tle(B, 'implement', RUN)], ORDER, garbage, { nowMs: B + 1000 })
    derive([tle(B, 'implement', RUN)], ORDER, 42, { nowMs: B + 1000 })
    derive([tle(B, 'implement', RUN)], ORDER, 'garbage', { nowMs: B + 1000 })
  } catch (e) { threw = e }
  ok(!threw, `handoff 畸形条目/非数组 handoffs 不抛错（threw=${threw && threw.message}）`)
}
section('S8c 空 timeline → 空对象（UI 不渲染徽标，软降级）')
{
  let out = null, threw = null
  try { out = derive([], ORDER, [], { nowMs: B + 1000 }) } catch (e) { threw = e }
  ok(!threw && out && typeof out === 'object' && Object.keys(out).length === 0,
    `空 timeline → {}（got ${JSON.stringify(out)}）`)
  let out2 = null
  try { out2 = derive(undefined, ORDER, undefined, { nowMs: B + 1000 }) } catch (e) { out2 = 'threw' }
  ok(out2 !== 'threw' && typeof out2 === 'object', 'timeline/handoffs 全缺省 → 空对象不炸')
}

/* ---------------------------------------------------------------- S9 秒/毫秒单位锚定（U9，P0 修正版） */
section('S9 单位锚定：epoch 秒×1000=ISO 同一瞬刻（真实对应值）')
{
  const EPOCH_SEC = 1720000000
  const EPOCH_ISO = '2024-07-03T09:46:40.000Z' // python datetime 实证：1720000000=该 ISO（09:06:40 是错的）
  ok(Date.parse(EPOCH_ISO) === EPOCH_SEC * 1000, 'fixture 自证：ISO 解析=秒×1000（对应关系本身正确）')
  const timeline = [tle(Date.parse(EPOCH_ISO), 'create_plan', RUN)]
  const handoffs = [{ stage: 'create_plan', ts: EPOCH_SEC + 60 }] // 晚 60 秒
  const out = derive(timeline, ORDER, handoffs, { nowMs: (EPOCH_SEC + 120) * 1000 })
  const r = roundsOf(out, 'create_plan')?.[0]
  ok(!!r, '轮存在')
  if (r) {
    ok(r.fromMs === EPOCH_SEC * 1000, `fromMs=秒×1000（got ${r.fromMs}）`)
    ok(r.toMs === (EPOCH_SEC + 60) * 1000, `toMs=秒×1000（got ${r.toMs}，漏 ×1000 会差 1000 倍）`)
  }
}

/* ---------------------------------------------------------------- S10 fmtDur 格式化契约（U11） */
section('S10 fmtDur：分段/省略 0 段/「—」')
{
  const cases = [
    [null, '—'], [undefined, '—'], [-1, '—'], [NaN, '—'],
    [0, '0s'], [999, '0s'], [59000, '59s'], [60000, '1m'], [61000, '1m 1s'],
    [125000, '2m 5s'], [3000000, '50m'], [3540000, '59m'],
    [3600000, '1h 0m'], [3660000, '1h 1m'], [90060000, '25h 1m'],
  ]
  let allOk = true
  for (const [input, want] of cases) {
    const got = fmtDur(input)
    if (got !== want) { allOk = false; console.log(`    fmtDur(${input}) got=${JSON.stringify(got)} want=${JSON.stringify(want)}`) }
  }
  ok(allOk, `fmtDur 14 例全中（<60s Xs / <60m Xm Ys 省 0 段 / ≥1h Xh Ym / null·负·NaN → —）`)
}

/* ---------------------------------------------------------------- S11 时钟回拨负差（U10） */
section('S11 时钟回拨：负差值不炸，fmtDur 显「—」')
{
  const timeline = [tle(B + 600000, 'merge', RUN)]
  // closedTs 早于开窗（时钟回拨/手工早关）→ toMs<fromMs
  const out = derive(timeline, ORDER, [], { nowMs: B + 600000, closedTs: sec(B) })
  const r = roundsOf(out, 'merge')?.[0]
  ok(!!r && r.toMs !== null && r.toMs < r.fromMs, `负差窗存在（toMs=${r && r.toMs} < fromMs=${r && r.fromMs}）`)
  if (r) ok(fmtDur(r.toMs - r.fromMs) === '—', 'fmtDur(负差) → —')
}

console.log(`\n${passed} passed, ${failed} failed, ${skipped} skipped`)
console.log(`SUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
